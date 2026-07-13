"""Rockchip Bootloader 构建策略 -- 替代 bootloader/rockchip/build.sh"""

import re
import shlex
import shutil
from pathlib import Path
from builder.base import ComponentBuilder


class RockchipBootloaderBuilder(ComponentBuilder):
    component = "bootloader"
    ARCH = "arm"
    DEFAULT_ARCH = "arm"
    DEFAULT_CROSS = ComponentBuilder.CROSS

    def _configure_build_context(self, config: dict) -> None:
        """为本次 U-Boot 构建解析 ARCH 与 CROSS_COMPILE。"""
        bootloader = config.get("bootloader", {}) or {}
        self.ARCH = bootloader.get("arch", self.DEFAULT_ARCH)
        self.CROSS = bootloader.get("cross_compile", self.DEFAULT_CROSS)

    def configure(self, src_dir: Path, config: dict):
        self._configure_build_context(config)
        # 预编 spi.img 板（见 compile）不自编 u-boot，跳过 defconfig 配置。
        if config["bootloader"].get("prebuilt_spi_image"):
            return
        # bootloader.defconfig 支持单字符串或 list（对齐 kernel.defconfig）：
        # list 中含 "=" 或 "# CONFIG_" 的项是 raw u-boot option（聚合后追加进
        # .config 再 olddefconfig 归一化），其余是 defconfig/fragment make 目标。
        # 让 SoC/board 直接在 bootloader.defconfig（或板级 +defconfig:<product>）
        # 写一行 CONFIG_X=y 即开 u-boot 选项，无需 patch 上游 defconfig 文件。
        defconfig = config["bootloader"]["defconfig"]
        if isinstance(defconfig, str):
            defconfig = [defconfig]
        targets = [d for d in defconfig
                   if "=" not in d and not d.lstrip().startswith("# CONFIG_")]
        raw_options = [d for d in defconfig
                       if "=" in d or d.lstrip().startswith("# CONFIG_")]
        # U-Boot 的 fragment target 会合并当前 .config。逐个 make 可保证 base
        # defconfig → SoC fragment → AMP fragment 的确定顺序，避免 -j 下并行 target
        # 同时改写 .config。
        for target in targets:
            self.make(src_dir, [target], arch=self.ARCH, cross=self.CROSS)
        if raw_options:
            self._apply_inline_defconfig(src_dir, raw_options)
        self._validate_amp_options(src_dir, config)

    @staticmethod
    def _validate_amp_options(src_dir: Path, config: dict) -> None:
        """AMP target 必须在最终 U-Boot .config 中成对保留两个选项。"""
        if not (config.get("amp") or {}).get("enabled", False):
            return
        config_path = src_dir / ".config"
        if not config_path.is_file():
            raise FileNotFoundError(
                f"U-Boot AMP 配置校验所需 .config 未生成: {config_path}")
        text = config_path.read_text()
        missing = [
            option for option in ("CONFIG_AMP=y", "CONFIG_ROCKCHIP_AMP=y")
            if option not in text.splitlines()
        ]
        if missing:
            raise ValueError(
                "U-Boot AMP 选项未成对保留: " + ", ".join(missing))

    def _apply_inline_defconfig(self, src_dir: Path, options: list):
        """把 bootloader.defconfig 里的 raw u-boot option 追加进 .config 再
        olddefconfig 归一化。u-boot 与内核同用 Kconfig，但其 defconfig 在 configs/、
        无内核 arch/<ARCH>/configs 的 fragment 布局，故用「append + olddefconfig」
        （而非 make <frag>.config）跨工具稳妥：olddefconfig 按 Kconfig 依赖解析
        select、丢弃 unmet-deps 项。在容器内追加（.config 由容器内 make 生成）。"""
        payload = "".join(o.rstrip("\n") + "\n" for o in options)
        self.docker.run(
            ["sh", "-c", "printf '%s' " + shlex.quote(payload) + " >> .config"],
            cwd=str(src_dir))
        self.make(src_dir, ["olddefconfig"], arch=self.ARCH, cross=self.CROSS)
        self._status(f"u-boot inline defconfig（{len(options)} 项 option）")

    def compile(self, src_dir: Path, config: dict):
        self._configure_build_context(config)
        ini_prefix = config["rkbin"]["ini_prefix"]
        prebuilt_spi_image = (config.get("bootloader") or {}).get(
            "prebuilt_spi_image")
        mkimage_chip = config["rkbin"].get("mkimage_chip")
        if not prebuilt_spi_image and not mkimage_chip:
            raise KeyError(
                "Rockchip SoC 配置缺少 rkbin.mkimage_chip 字段；"
                "该字段是 mkimage 打包 idbloader 时传给 BootROM 的 chip 标签，"
                "必须在 SoC config 显式声明（如 RK3566 用 'rk3568'，"
                "RK3588 用 'rk3588'）。"
            )
        firmware_dir = self.source.ensure_firmware("rockchip", config)

        # 预编 spi.img 板（RK3576 ROCK 4D）：整套 SPI 启动固件用 radxa bsp 预编的
        # spi.img（board 声明 bootloader.prebuilt_spi_image，flash.py 直接刷之），
        # flange 不自编 u-boot —— 此处只产 DB 刷写阶段要用的 miniloader.bin，跳过
        # u-boot/idbloader/itb 自编。为何不自编详见 openspec design「bootloader 根因」。
        if prebuilt_spi_image:
            loader_ini = self._loader_ini_path(firmware_dir, config)
            self.docker.run([
                str(firmware_dir / "tools" / "boot_merger"), str(loader_ini),
            ], cwd=str(firmware_dir))
            self._firmware_dir = firmware_dir
            self._ini_prefix = ini_prefix
            self._loader_ini = loader_ini
            return

        jobs = config.get("jobs", 0)

        # RK3506 等 ARM32 SoC 的 TOS INI 只有 TOSTA/ADDR；ARM64 路径仍解析
        # BL31/BL32。两者都由显式 trust_mode 路由，不伪造不存在的 BL31。
        trust_mode = config["bootloader"].get("trust_mode", "bl31")
        trust_ini = self._trust_ini_path(firmware_dir, config)
        if trust_mode == "tos":
            tee, tee_addr = self._parse_tos_ini(trust_ini, firmware_dir)
            bl31 = None
            bl32 = tee
        elif trust_mode == "bl31":
            bl31, bl32 = self._parse_trust_ini(trust_ini, firmware_dir)
            tee_addr = None
        else:
            raise ValueError(
                f"bootloader.trust_mode 非法: {trust_mode!r}（须为 bl31 或 tos）")

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
        extra = []
        if bl31:
            shutil.copy2(bl31, src_dir / "bl31.elf")
            extra.append(f"BL31={src_dir / 'bl31.elf'}")
        if bl32:
            shutil.copy2(bl32, src_dir / "tee.bin")
            extra.append(f"TEE={src_dir / 'tee.bin'}")

        # 第一步：默认 target 生成 u-boot/u-boot.dtb 等基础产物
        extra.append("KCFLAGS=-Wno-error")
        self.make(src_dir, [],
                  arch=self.ARCH, cross=self.CROSS, jobs=jobs, extra=extra,
                  label="编译 U-Boot...")
        # 第二步：基于 u-boot.dtb 打包 u-boot.itb (FIT image)
        fit_extra = list(extra)
        fit_its = None
        if trust_mode == "tos":
            fit_its = self._render_tos_fit_its(src_dir, tee_addr)
            fit_extra.append(f"U_BOOT_ITS={fit_its}")
        fit_pack = config["bootloader"].get("fit_pack")
        if fit_pack:
            if fit_its is None:
                raise ValueError(
                    "bootloader.fit_pack 当前要求 trust_mode=tos，"
                    "以便取得 make_fit_optee.sh 生成的 ITS")
            self._pack_vendor_fit(src_dir, fit_its, fit_pack)
        else:
            self.make(src_dir, ["u-boot.itb"],
                      arch=self.ARCH, cross=self.CROSS, jobs=jobs,
                      extra=fit_extra,
                      label="打包 u-boot.itb...")

        loader_ini = self._loader_ini_path(firmware_dir, config)
        run_ini = loader_ini

        # boot_merger SoC 可把 FlashBoot 换成**自编 SPL**（与 proper 同源）。
        # RK3506 原厂 RK_UBOOT_SPL=y / --spl-new 明确采用该路径；RK3576 的根因
        # （机制 + 寄存器证据，上板实测）则是让 UFS DMA 能访问 DDR 的私有
        # 防火墙 SGRF_DOMAIN_CON3（FW_SYS_SGRF）只在 SPL 阶段 arch_cpu_init 设置、
        # proper 永不重设 —— 故 UFS 读 buffer 能否被 DMA 落由跑过的 SPL 决定。混用
        # rkbin 预编 SPL（另一棵 u-boot 树）+ 自编 proper → SGRF 域授权与 proper 不
        # 自洽 → SCSI READ 数据静默不落 buffer → proper 读 UFS GPT 拿残渣 →
        # Synchronous Abort。官方 bsp 即 sed RK3576MINIALL.ini 的 FlashBoot=自编
        # spl/u-boot-spl.bin（FlashBoost/FlashData 仍 rkbin），再 boot_merger。详见
        # openspec selfbuild-rk3576-spi-image design。
        use_boot_merger = (
            config["bootloader"].get("idbloader_method") == "boot_merger")
        use_selfbuilt_spl = config["bootloader"].get(
            "idbloader_selfbuilt_spl", use_boot_merger)
        if use_boot_merger and use_selfbuilt_spl:
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
        #  - 声明 idbloader_method=="boot_merger" 的 SoC：boot_merger 按（可改
        #    FlashBoot 的）ini 装配 NEWIDB；RK3506 是 DDR + SPL，RK3576 还含 boost。
        #    此处整段跳过 mkimage。
        #  - 其他 RK35xx：mkimage -T rksd -d ddr:spl 产 idbloader.img（rkbin 预编 blob）。
        # 详见 openspec selfbuild-rk3576-spi-image design Decision 1。
        if not use_boot_merger:
            ddr_bin, spl_bin = self._parse_loader_ini(loader_ini, firmware_dir)
            self.docker.run([
                str(src_dir / "tools" / "mkimage"),
                "-n", mkimage_chip, "-T", "rksd",
                "-d", f"{ddr_bin}:{spl_bin}",
                str(src_dir / "idbloader.img"),
            ])

        # 生成 miniloader.bin（DB/UL 刷写阶段用）；boot_merger 同时产出 [OUTPUT]
        # IDB_PATH 的 NEWIDB idblock。run_ini 在启用 selfbuilt_spl 时是改过
        # FlashBoot 的副本，否则为 stock。
        self.docker.run([
            str(firmware_dir / "tools" / "boot_merger"),
            str(run_ini),
        ], cwd=str(firmware_dir))

        # boot_merger：把产出的 idblock 拷为 idbloader.img 供 collect 使用。
        # IDB_PATH 含版本号，必须动态解析。
        if use_boot_merger:
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
        self._loader_ini = loader_ini

    def _loader_ini_path(self, firmware_dir: Path, config: dict) -> Path:
        """按显式文件名或兼容 prefix 规则解析 RKBOOT INI。"""
        rkbin = config["rkbin"]
        name = rkbin.get("loader_ini")
        if not name:
            name = f"{rkbin['ini_prefix']}MINIALL.ini"
        path = firmware_dir / "RKBOOT" / name
        if not path.is_file():
            raise FileNotFoundError(f"Rockchip loader INI 不存在: {path}")
        return path

    def _trust_ini_path(self, firmware_dir: Path, config: dict) -> Path:
        """按显式文件名或兼容 prefix 规则解析 RKTRUST INI。"""
        rkbin = config["rkbin"]
        name = rkbin.get("trust_ini")
        if not name:
            prefix = rkbin.get("trust_ini_prefix", rkbin["ini_prefix"])
            name = f"{prefix}TRUST.ini"
        path = firmware_dir / "RKTRUST" / name
        if not path.is_file():
            raise FileNotFoundError(f"Rockchip trust/TOS INI 不存在: {path}")
        return path

    def _render_tos_fit_its(self, src_dir: Path, tee_addr: str) -> Path:
        """调用 make_fit_optee.sh，以 TOS INI 地址渲染临时 U-Boot ITS。"""
        generator = (
            src_dir / "arch" / "arm" / "mach-rockchip"
            / "make_fit_optee.sh"
        )
        if not generator.is_file():
            raise FileNotFoundError(f"U-Boot FIT generator 不存在: {generator}")
        result = self.docker.run(
            [str(generator), "-t", tee_addr],
            cwd=str(src_dir),
            capture=True,
        )
        its = src_dir / "u-boot-flange-tos.its"
        its.write_text(result.stdout)
        if not its.read_text().strip():
            raise ValueError("make_fit_optee.sh 未生成 ITS 内容")
        return its

    def _pack_vendor_fit(
        self,
        src_dir: Path,
        fit_its: Path,
        pack: dict,
    ) -> None:
        """复刻 Rockchip ``scripts/fit.sh`` 的 U-Boot FIT 输出。

        vendor 脚本不是直接使用 ``make u-boot.itb`` 的紧凑输出：它先以
        ``mkimage -E -p <offset>`` 固定 external data（外置数据）起点，再按
        ``CONFIG_SPL_FIT_IMAGE_KB`` 和 ``CONFIG_SPL_FIT_IMAGE_MULTIPLE`` 把 FIT
        填充成固定槽位并保留多份副本。SPI NAND 的 SPL 会按同一槽宽逐份尝试，
        因此不能只写第一份紧凑 FIT。
        """
        offset = str(pack.get("external_data_offset", "0x1200"))
        slot_size_kb = self._fit_pack_value(
            src_dir,
            pack,
            "slot_size_kb",
            "CONFIG_SPL_FIT_IMAGE_KB",
        )
        copies = self._fit_pack_value(
            src_dir,
            pack,
            "copies",
            "CONFIG_SPL_FIT_IMAGE_MULTIPLE",
        )
        output = src_dir / "u-boot.itb"
        self.docker.run(
            [
                str(src_dir / "tools" / "mkimage"),
                "-f", str(fit_its),
                "-E", "-p", offset,
                str(output),
            ],
            cwd=str(src_dir),
            label="按 vendor 布局打包 u-boot.itb...",
        )
        self._repeat_fit_slots(output, slot_size_kb, copies)
        self._status(
            f"u-boot FIT（offset={offset}，{slot_size_kb} KiB × {copies}）")

    @staticmethod
    def _fit_pack_value(
        src_dir: Path,
        pack: dict,
        field: str,
        kconfig_name: str,
    ) -> int:
        """读取并交叉校验 vendor FIT 槽位参数。"""
        config_text = (src_dir / ".config").read_text()
        match = re.search(
            rf"(?m)^{re.escape(kconfig_name)}=(\d+)$",
            config_text,
        )
        if not match:
            raise ValueError(f"最终 U-Boot .config 缺少 {kconfig_name}")
        actual = int(match.group(1))
        expected = int(pack.get(field, actual))
        if actual != expected:
            raise ValueError(
                f"bootloader.fit_pack.{field}={expected} 与最终 "
                f"{kconfig_name}={actual} 不一致")
        if actual <= 0:
            raise ValueError(f"{kconfig_name} 必须大于 0，实际为 {actual}")
        return actual

    @staticmethod
    def _repeat_fit_slots(path: Path, slot_size_kb: int, copies: int) -> None:
        """把一个 FIT 填充到固定槽宽并复制为 SPL 可回退的多副本镜像。"""
        payload = path.read_bytes()
        slot_size = slot_size_kb * 1024
        if len(payload) > slot_size:
            raise ValueError(
                f"U-Boot FIT {len(payload)} bytes 超过单槽 "
                f"{slot_size} bytes")
        slot = payload + bytes(slot_size - len(payload))
        path.write_bytes(slot * copies)

    def _parse_trust_ini(self, ini_path: Path, fw_dir: Path):
        """解析 RKTRUST INI 提取 BL31/BL32 固件路径。"""
        content = ini_path.read_text()
        bl31 = self._extract_ini_path(content, "BL31")
        bl32 = self._extract_ini_path(content, "BL32")
        bl31_path = fw_dir / bl31 if bl31 else None
        bl32_path = (fw_dir / bl32) if bl32 else None
        if not bl31_path or not bl31_path.exists():
            raise FileNotFoundError(f"BL31 固件未找到: {bl31_path}")
        if bl32_path and not bl32_path.exists():
            raise FileNotFoundError(f"BL32 固件未找到: {bl32_path}")
        return bl31_path, bl32_path

    def _parse_tos_ini(self, ini_path: Path, fw_dir: Path):
        """解析 RKTRUST TOS INI 的 TOSTA/TOS 与 ADDR。"""
        content = ini_path.read_text()
        tos = self._extract_section_value(content, "TOS", "TOSTA")
        if not tos:
            tos = self._extract_section_value(content, "TOS", "TOS")
        address = self._extract_section_value(content, "TOS", "ADDR")
        if not tos or not address:
            raise ValueError(f"无法从 {ini_path} 解析 TOSTA/TOS 与 ADDR")
        tos_path = fw_dir / tos
        if not tos_path.is_file():
            raise FileNotFoundError(f"TOS 固件未找到: {tos_path}")
        return tos_path, address

    @staticmethod
    def _extract_section_value(content: str, section: str, key: str):
        """从普通 INI section 提取键值（不依赖 ConfigParser 大小写规则）。"""
        in_section = False
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if line == f"[{section}]":
                in_section = True
                continue
            if in_section and line.startswith("["):
                break
            if in_section and line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
        return None

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
        loader_ini = self._loader_ini
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
