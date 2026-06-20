"""Rockchip Bootloader 构建策略 -- 替代 bootloader/rockchip/build.sh"""

import shutil
from pathlib import Path
from builder.base import ComponentBuilder


class RockchipBootloaderBuilder(ComponentBuilder):
    component = "bootloader"
    ARCH = "arm"
    CROSS = "aarch64-linux-gnu-"

    def configure(self, src_dir: Path, config: dict):
        # 预编 spi.img 板（见 compile）不自编 u-boot，跳过 defconfig 配置。
        if config["bootloader"].get("prebuilt_spi_image"):
            return
        defconfig = config["bootloader"]["defconfig"]
        self.make(src_dir, [defconfig], arch=self.ARCH, cross=self.CROSS)

    def compile(self, src_dir: Path, config: dict):
        ini_prefix = config["rkbin"]["ini_prefix"]
        firmware_dir = self.source.ensure_firmware("rockchip", config)

        # 预编 spi.img 板（RK3576 ROCK 4D）：整套 SPI 启动固件用 radxa bsp 预编的
        # spi.img（board 声明 bootloader.prebuilt_spi_image，flash.py 直接刷之），
        # flange 不自编 u-boot —— 此处只产 DB 刷写阶段要用的 miniloader.bin，跳过
        # u-boot/idbloader/itb 自编。为何不自编详见 openspec design「bootloader 根因」。
        if config["bootloader"].get("prebuilt_spi_image"):
            loader_ini = firmware_dir / "RKBOOT" / f"{ini_prefix}MINIALL.ini"
            self.docker.run([
                str(firmware_dir / "tools" / "boot_merger"), str(loader_ini),
            ], cwd=str(firmware_dir))
            self._firmware_dir = firmware_dir
            self._ini_prefix = ini_prefix
            return

        trust_prefix = config["rkbin"].get("trust_ini_prefix", ini_prefix)
        mkimage_chip = config["rkbin"].get("mkimage_chip")
        if not mkimage_chip:
            raise KeyError(
                "Rockchip SoC 配置缺少 rkbin.mkimage_chip 字段；"
                "该字段是 mkimage 打包 idbloader 时传给 BootROM 的 chip 标签，"
                "必须在 SoC config 显式声明（如 RK3566 用 'rk3568'，RK3588 用 'rk3588'）。"
            )
        jobs = config.get("jobs", 0)

        # 解析 RKTRUST INI -- 提取 BL31/BL32
        trust_ini = firmware_dir / "RKTRUST" / f"{trust_prefix}TRUST.ini"
        bl31, bl32 = self._parse_trust_ini(trust_ini, firmware_dir)

        # v2024.10 等老 u-boot 的 decode_bl31.py shebang 写死 python2，而构建容器只装
        # python3 → 该脚本跑不起来、拆不出 bl31_0x*.bin、BL31 漏出 FIT。这是独立于任何
        # 板的通用构建缺陷，改 shebang 即修（脚本内容 py3 完全兼容，幂等：python3 版
        # no-op）。注：RK3576 ROCK 4D **不走自编路线**（锁 prebuilt spi.img），不受此
        # 影响；其 UFS 崩溃的真因是 idbloader 缺 rk3576_boost，与 BL31 无关（见 board）。
        decode = src_dir / "arch" / "arm" / "mach-rockchip" / "decode_bl31.py"
        if decode.exists():
            _t = decode.read_text()
            if _t.startswith("#!/usr/bin/env python2"):
                decode.write_text(_t.replace(
                    "#!/usr/bin/env python2", "#!/usr/bin/env python3", 1))

        # 复制固件到 U-Boot 源码目录
        shutil.copy2(bl31, src_dir / "bl31.elf")
        extra = [f"BL31={src_dir / 'bl31.elf'}"]
        if bl32:
            shutil.copy2(bl32, src_dir / "tee.bin")
            extra.append(f"TEE={src_dir / 'tee.bin'}")

        # 第一步：默认 target 生成 u-boot/u-boot.dtb 等基础产物
        extra.append("KCFLAGS=-Wno-error")
        self.make(src_dir, [],
                  arch=self.ARCH, cross=self.CROSS, jobs=jobs, extra=extra,
                  label="编译 U-Boot...")
        # 第二步：基于 u-boot.dtb 打包 u-boot.itb (FIT image)
        self.make(src_dir, ["u-boot.itb"],
                  arch=self.ARCH, cross=self.CROSS, jobs=jobs, extra=extra,
                  label="打包 u-boot.itb...")

        # 解析 RKBOOT INI -- 生成 idbloader.img
        loader_ini = firmware_dir / "RKBOOT" / f"{ini_prefix}MINIALL.ini"
        ddr_bin, spl_bin = self._parse_loader_ini(loader_ini, firmware_dir)

        # SPL 来源：默认用 rkbin 预编 SPL（vendor miniloader 风格，eMMC/SD 板可用）。
        # UFS 板须用 u-boot **自编** SPL（spl/u-boot-spl.bin）：保证 SPL 与 proper
        # 同源，UFS 控制器从 SPL 到 proper 的交接状态自洽。混用「rkbin 预编 SPL +
        # 自编 proper」时，proper 的 ufshcd-rockchip 清不掉 rkbin SPL 残留的控制器
        # 状态 → UIC 超时、SCSI scan 不完成 → 读 UFS GPT 拿到垃圾 → part_test_efi
        # 崩（RK3576 ROCK 4D 实测）。board 设 bootloader.idbloader_spl="uboot" 切换。
        if config["bootloader"].get("idbloader_spl") == "uboot":
            spl_bin = src_dir / "spl" / "u-boot-spl.bin"
            if not spl_bin.exists():
                raise FileNotFoundError(
                    f"idbloader_spl=uboot 但未找到自编 SPL: {spl_bin}"
                    "（需 defconfig 开 CONFIG_SPL，且 make 已构建 SPL）")

        self.docker.run([
            str(src_dir / "tools" / "mkimage"),
            "-n", mkimage_chip, "-T", "rksd",
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
        # 从 RKBOOT INI 的 [OUTPUT] 段提取 miniloader 实际文件名
        loader_ini = firmware_dir / "RKBOOT" / f"{ini_prefix}MINIALL.ini"
        output_name = self._extract_output_path(loader_ini.read_text())
        miniloader = firmware_dir / output_name if output_name else None
        if miniloader and not miniloader.exists():
            miniloader = None
        # 预编 spi.img 板只产 miniloader（DB 阶段用），无自编 idbloader/u-boot.itb。
        if config["bootloader"].get("prebuilt_spi_image"):
            return {"miniloader": miniloader}
        return {
            "bootloader": src_dir / "u-boot.itb",
            "idbloader": src_dir / "idbloader.img",
            "miniloader": miniloader,
        }

    def _extract_output_path(self, content: str):
        """从 INI 的 [OUTPUT] 段提取 PATH 值。"""
        in_section = False
        for line in content.splitlines():
            line = line.strip()
            if line == "[OUTPUT]":
                in_section = True
                continue
            if in_section and line.startswith("["):
                in_section = False
                continue
            if in_section and line.startswith("PATH="):
                return line.split("=", 1)[1].strip()
        return None
