"""Rockchip Bootloader 构建策略 -- 替代 bootloader/rockchip/build.sh"""

import shutil
from pathlib import Path
from builder.base import ComponentBuilder


class RockchipBootloaderBuilder(ComponentBuilder):
    component = "bootloader"
    ARCH = "arm"
    CROSS = "aarch64-linux-gnu-"

    def configure(self, src_dir: Path, config: dict):
        defconfig = config["bootloader"]["defconfig"]
        self.make(src_dir, [defconfig], arch=self.ARCH, cross=self.CROSS)

    def compile(self, src_dir: Path, config: dict):
        firmware_dir = self.source.ensure_firmware("rockchip", config)
        ini_prefix = config["rkbin"]["ini_prefix"]
        trust_prefix = config["rkbin"].get("trust_ini_prefix", ini_prefix)
        jobs = config.get("jobs", 0)

        # 解析 RKTRUST INI -- 提取 BL31/BL32
        trust_ini = firmware_dir / "RKTRUST" / f"{trust_prefix}TRUST.ini"
        bl31, bl32 = self._parse_trust_ini(trust_ini, firmware_dir)

        # 复制固件到 U-Boot 源码目录
        shutil.copy2(bl31, src_dir / "bl31.elf")
        extra = [f"BL31={src_dir / 'bl31.elf'}"]
        if bl32:
            shutil.copy2(bl32, src_dir / "tee.bin")
            extra.append(f"TEE={src_dir / 'tee.bin'}")

        # 编译 U-Boot（默认 target 会生成 u-boot.itb 等全部产物）
        extra.append("KCFLAGS=-Wno-error")
        self.make(src_dir, [],
                  arch=self.ARCH, cross=self.CROSS, jobs=jobs, extra=extra,
                  label="编译 U-Boot...")

        # 解析 RKBOOT INI -- 生成 idbloader.img
        loader_ini = firmware_dir / "RKBOOT" / f"{ini_prefix}MINIALL.ini"
        ddr_bin, spl_bin = self._parse_loader_ini(loader_ini, firmware_dir)

        self.docker.run([
            str(src_dir / "tools" / "mkimage"),
            "-n", "rk3568", "-T", "rksd",
            "-d", f"{ddr_bin}:{spl_bin}",
            str(src_dir / "idbloader.img"),
        ])

        # 生成 miniloader.bin
        self.docker.run([
            str(firmware_dir / "tools" / "boot_merger"),
            str(loader_ini),
        ], cwd=str(firmware_dir))

        self._firmware_dir = firmware_dir
        self._ini_prefix = ini_prefix

    def _parse_trust_ini(self, ini_path: Path, fw_dir: Path):
        """解析 RKTRUST INI 提取 BL31/BL32 固件路径。"""
        content = ini_path.read_text()
        bl31 = self._extract_ini_path(content, "BL31")
        bl32 = self._extract_ini_path(content, "BL32")
        bl31_path = fw_dir / bl31 if bl31 else None
        bl32_path = (fw_dir / bl32) if bl32 else None
        if not bl31_path or not bl31_path.exists():
            raise FileNotFoundError(f"BL31 固件未找到: {bl31_path}")
        return bl31_path, bl32_path

    def _parse_loader_ini(self, ini_path: Path, fw_dir: Path):
        """解析 RKBOOT INI 提取 DDR/SPL 路径。"""
        content = ini_path.read_text()
        # FlashData = DDR bin, FlashBoot = SPL/miniloader bin
        ddr_rel = None
        spl_rel = None
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("FlashData="):
                ddr_rel = line.split("=", 1)[1].strip()
            elif line.startswith("FlashBoot="):
                spl_rel = line.split("=", 1)[1].strip()
        if not ddr_rel or not spl_rel:
            raise ValueError(f"无法从 {ini_path} 解析 FlashData/FlashBoot")
        return fw_dir / ddr_rel, fw_dir / spl_rel

    def _extract_ini_path(self, content: str, section_prefix: str):
        """从 INI 内容提取指定 section 的 PATH 值。"""
        in_section = False
        for line in content.splitlines():
            line = line.strip()
            if line.startswith(f"[{section_prefix}_OPTION"):
                in_section = True
                continue
            if in_section and line.startswith("["):
                in_section = False
                continue
            if in_section and line.startswith("PATH="):
                return line.split("=", 1)[1].strip()
        return None

    def collect(self, src_dir: Path, config: dict) -> dict:
        firmware_dir = self._firmware_dir
        ini_prefix = self._ini_prefix
        miniloader_candidates = list(
            firmware_dir.glob(f"{ini_prefix}_loader_v*.bin"))
        miniloader = miniloader_candidates[0] if miniloader_candidates else None
        return {
            "bootloader": src_dir / "u-boot.itb",
            "idbloader": src_dir / "idbloader.img",
            "miniloader": miniloader,
        }
