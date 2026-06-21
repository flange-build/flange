"""Rockchip Bootloader 构建策略 -- 替代 bootloader/rockchip/build.sh"""

import re
import shutil
from pathlib import Path
from builder.base import ComponentBuilder


class RockchipBootloaderBuilder(ComponentBuilder):
    component = "bootloader"
    ARCH = "arm"

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

        # 老 rockchip u-boot 的 decode_bl31.py shebang 写死 python2，而构建容器只装
        # python3 → 该脚本跑不起来、拆不出 bl31_0x*.bin、BL31 漏出 FIT。独立于任何板的
        # 通用构建缺陷，改 shebang 即修（脚本内容 py3 完全兼容，幂等：python3 版 no-op）。
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

        loader_ini = firmware_dir / "RKBOOT" / f"{ini_prefix}MINIALL.ini"
        run_ini = loader_ini

        # RK3576: idbloader 的 SPL 改用**自编**（与 proper 同源），复刻官方 prebuilt。
        # 根因（机制 + 寄存器证据，上板实测）：RK3576 让 UFS DMA 能访问 DDR 的私有
        # 防火墙 SGRF_DOMAIN_CON3（FW_SYS_SGRF）只在 SPL 阶段 arch_cpu_init 设置、
        # proper 永不重设 —— 故 UFS 读 buffer 能否被 DMA 落由跑过的 SPL 决定。混用
        # rkbin 预编 SPL（另一棵 u-boot 树）+ 自编 proper → SGRF 域授权与 proper 不
        # 自洽 → SCSI READ 数据静默不落 buffer → proper 读 UFS GPT 拿残渣 →
        # Synchronous Abort。官方 bsp 即 sed RK3576MINIALL.ini 的 FlashBoot=自编
        # spl/u-boot-spl.bin（FlashBoost/FlashData 仍 rkbin），再 boot_merger。详见
        # openspec selfbuild-rk3576-spi-image design。
        if config["bootloader"].get("idbloader_method") == "boot_merger":
            self_spl = src_dir / "spl" / "u-boot-spl.bin"
            if not self_spl.exists():
                raise FileNotFoundError(
                    f"boot_merger 须自编 SPL 但未找到 {self_spl}"
                    "（需 defconfig 开 CONFIG_SPL，make 已产 spl/u-boot-spl.bin）")
            # 仅把 FlashBoot 段换成自编 SPL 绝对路径；FlashBoost(boost)/FlashData(DDR)
            # 仍 rkbin、相对 firmware_dir（boot_merger cwd=firmware_dir）。写到 src_dir
            # 副本 ini，不污染 rkbin 仓库的 stock ini。^FlashBoot= 不会误匹配 FlashBoost=。
            text = re.sub(r"(?m)^FlashBoot=.*$",
                          f"FlashBoot={self_spl}", loader_ini.read_text())
            run_ini = src_dir / f"{ini_prefix}MINIALL_selfspl.ini"
            run_ini.write_text(text)

        # idbloader 装配方式按 SoC 分流：
        #  - RK3576（idbloader_method=="boot_merger"）：boot_merger 按（改了 FlashBoot
        #    的）ini 装配 idbloader（含 boost + 自编 SPL）；此处整段跳过 mkimage。
        #  - 其他 RK35xx：mkimage -T rksd -d ddr:spl 产 idbloader.img（rkbin 预编 blob）。
        # 详见 openspec selfbuild-rk3576-spi-image design Decision 1。
        if config["bootloader"].get("idbloader_method") != "boot_merger":
            ddr_bin, spl_bin = self._parse_loader_ini(loader_ini, firmware_dir)
            self.docker.run([
                str(src_dir / "tools" / "mkimage"),
                "-n", mkimage_chip, "-T", "rksd",
                "-d", f"{ddr_bin}:{spl_bin}",
                str(src_dir / "idbloader.img"),
            ])

        # 生成 miniloader.bin（DB 刷写阶段用）；boot_merger 同时产出 [OUTPUT] IDB_PATH
        # 的 NEWIDB idblock，供 RK3576 idbloader 取用。run_ini：RK3576=改过 FlashBoot 的
        # 副本（自编 SPL），其他 SoC=stock。
        self.docker.run([
            str(firmware_dir / "tools" / "boot_merger"),
            str(run_ini),
        ], cwd=str(firmware_dir))

        # RK3576：idbloader = boot_merger 产出的 idblock（含 boost + 自编 SPL），拷为
        # idbloader.img 供 collect → build_spi_image 取用。IDB_PATH 含版本号，动态解析。
        if config["bootloader"].get("idbloader_method") == "boot_merger":
            idb_name = self._extract_idb_path(run_ini.read_text())
            if not idb_name:
                raise ValueError(
                    f"idbloader_method=boot_merger 但 {run_ini} 无 [OUTPUT] IDB_PATH")
            idb_src = firmware_dir / idb_name
            if not idb_src.exists():
                raise FileNotFoundError(f"boot_merger 未产出 idblock: {idb_src}")
            shutil.copy2(idb_src, src_dir / "idbloader.img")

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

    def _extract_idb_path(self, content: str):
        """从 INI [OUTPUT] 段提取 IDB_PATH（boot_merger 产出的 idblock 文件名）。

        用精确 `IDB_PATH=` 前缀匹配，与 `_extract_output_path` 的 `PATH=`
        互不误命中（'IDB_PATH='.startswith('PATH=') 为 False，反之亦然）。
        """
        in_section = False
        for line in content.splitlines():
            line = line.strip()
            if line == "[OUTPUT]":
                in_section = True
                continue
            if in_section and line.startswith("["):
                in_section = False
                continue
            if in_section and line.startswith("IDB_PATH="):
                return line.split("=", 1)[1].strip()
        return None
