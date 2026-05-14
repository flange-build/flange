"""Amlogic Bootloader 构建策略。

mainline u-boot 编译产出 ``u-boot.bin``，再通过 LibreELEC/amlogic-boot-fip
仓库的 ``build-fip.sh <board_dir> <u-boot.bin> <out>`` 拼装 FIP（含 BL2
SIG / BL30+BL301 加密 / BL31 加密 / BL33 加密 / DDR fw 嵌入），最后用
仓库内 ``aml_encrypt_g12a --bootsd`` 派生 SD/eMMC 可启动镜像
``u-boot.bin.sd.bin``，并通过 ``--bootusb`` 派生 USB BL2/TPL（pyamlboot
推送 MaskROM 用）。

字段分层：
- SoC 层 ``bootloader.fip_tool`` / ``fip_family_inc`` —— 工具与 family include
- Board 层 ``bootloader.fip_board_dir`` —— amlogic-boot-fip 仓库内 board 子目录名
"""

import shutil
from pathlib import Path

from builder.base import ComponentBuilder
from builder.paths import COMPONENTS_ROOT


class AmlogicBootloaderBuilder(ComponentBuilder):
    component = "bootloader"
    # u-boot 把 ARM32 / ARM64 板都放在 arch/arm/ 树下，ARCH 总是传 ``arm``；
    # 64-bit 由 CROSS_COMPILE 区分（仅 kernel 走 ARCH=arm64）。误传
    # ARCH=arm64 时 u-boot Makefile 找不到 arch/arm64/include/asm/arch-...
    # 目录，create_symlink 阶段 ln 失败。
    ARCH = "arm"
    CROSS = "aarch64-linux-gnu-"

    def configure(self, src_dir: Path, config: dict):
        """合并 defconfig 列表。

        SoC 层 ``bootloader.defconfig`` 是 list 形式，按序逐个 ``make
        <name>``：先 base defconfig（如 ``khadas-vim3l_defconfig``），再叠加
        fragment（如 ``flange_fastboot.config``）。fragment 在 configure
        阶段从平台/SoC 层的 ``patches/bootloader/`` 复制到 u-boot 源码树
        ``configs/`` 下，由 u-boot Kbuild 的 ``%.config`` 规则合并。
        """
        self._stage_fragments(src_dir, config)
        defconfig = config["bootloader"]["defconfig"]
        if isinstance(defconfig, str):
            defconfig = [defconfig]
        for dc in defconfig:
            self.make(src_dir, [dc], arch=self.ARCH, cross=self.CROSS)

    def _stage_fragments(self, src_dir: Path, config: dict):
        """把 defconfig list 中以 ``.config`` 结尾的 fragment 复制到 u-boot
        ``configs/``。

        来源按优先级遍历：board → SoC → platform 各自的
        ``patches/bootloader/<fragment>``，首个命中的版本生效。fragment
        缺失视为致命错误（fail-fast，避免 make 阶段以"target 不存在"形式
        报错而难定位）。
        """
        defconfig = config["bootloader"]["defconfig"]
        if isinstance(defconfig, str):
            return
        platform = config["platform"]
        soc = config["soc"]
        board = config["board"]
        # 用 paths.py 暴露的绝对锚点，避免依赖调用时 cwd（ProjectSpec §9）。
        search_dirs = [
            COMPONENTS_ROOT / "board" / board / "patches" / "bootloader",
            COMPONENTS_ROOT / "platform" / platform / soc / "patches" / "bootloader",
            COMPONENTS_ROOT / "platform" / platform / "patches" / "bootloader",
        ]
        configs_dir = src_dir / "configs"
        configs_dir.mkdir(parents=True, exist_ok=True)
        for name in defconfig:
            if not name.endswith(".config"):
                continue
            src = self._find_fragment(name, search_dirs)
            if src is None:
                searched = ", ".join(str(d) for d in search_dirs)
                raise FileNotFoundError(
                    f"defconfig fragment 未找到: {name}（已搜索 {searched}）")
            shutil.copy2(src, configs_dir / name)
            self._status(f"defconfig fragment 就位: {name}")

    @staticmethod
    def _find_fragment(name: str, search_dirs: list) -> Path | None:
        for d in search_dirs:
            candidate = d / name
            if candidate.is_file():
                return candidate
        return None

    def compile(self, src_dir: Path, config: dict):
        """编译 u-boot → build-fip.sh 拼装 → aml_encrypt_g12a 派生。

        三段式：
          1. ``make`` 出 ``u-boot.bin``（mainline u-boot 标准产物）
          2. ``build-fip.sh <board_dir> <u-boot.bin> <out>`` 把 vendor blob
             与 u-boot proper 拼成 FIP 镜像（``<out>/u-boot.bin``）
          3. ``aml_encrypt_g12a --bootsd`` 派生 SD/eMMC 启动镜像；
             ``--bootusb`` 派生 USB BL2/TPL（pyamlboot 推送）

        所有产物落在 ``<src_dir>/fip/<board_dir>/`` 下，collect 阶段引用
        其中三个具名文件。
        """
        jobs = config.get("jobs", 0)
        self.make(src_dir, [], arch=self.ARCH, cross=self.CROSS, jobs=jobs,
                  label="编译 U-Boot...")

        # 通过 ensure_extra 的 from_repo 路由，复用 SoC config 的命名仓库
        # repos["amlogic-boot-fip"]，与 u-boot 共用同一份 .build/sources/repos/
        # 缓存，不重复 clone。
        fip_src = self.source.ensure_extra(
            "amlogic-boot-fip", {"from_repo": "amlogic-boot-fip"},
            config=config)
        bl_cfg = config["bootloader"]
        board_dir = bl_cfg.get("fip_board_dir")
        if not board_dir:
            raise KeyError(
                "Amlogic bootloader 构建缺少 bootloader.fip_board_dir；"
                "该字段是 LibreELEC/amlogic-boot-fip 仓库内 board 子目录名"
                "（如 'khadas-vim3l'），由 board config 声明（不在 SoC 层）。"
            )
        fip_tool = bl_cfg.get("fip_tool", "aml_encrypt_g12a")

        out_dir = src_dir / "fip" / board_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        u_boot_bin = src_dir / "u-boot.bin"

        # build-fip.sh 是仓库顶层入口脚本，参数序列：board / u-boot.bin / out
        self._status("FIP 拼装...")
        self.docker.run(
            ["bash", str(fip_src / "build-fip.sh"),
             board_dir, str(u_boot_bin), str(out_dir)],
            cwd=str(fip_src),
            label="build-fip.sh ...",
        )

        # aml_encrypt_g12a 二进制位于 board 子目录内（每个 board 各自一份）
        encrypt_tool = fip_src / board_dir / fip_tool
        fip_image = out_dir / "u-boot.bin"

        # SD/eMMC 启动镜像：boot0 hw 分区写入 offset 0x200
        self._status("派生 SD-bootable 镜像...")
        self.docker.run(
            [str(encrypt_tool), "--bootsd",
             "--infile", str(fip_image),
             "--output", str(fip_image) + ".sd.bin"],
            label="aml_encrypt_g12a --bootsd",
        )

        # USB BL2/TPL：pyamlboot 推 MaskROM 用，--bootusb 一次产出两个文件
        # （u-boot.bin.usb.bl2 / u-boot.bin.usb.tpl），输出名以 --output 为
        # 前缀
        self._status("派生 USB BL2/TPL...")
        self.docker.run(
            [str(encrypt_tool), "--bootusb",
             "--infile", str(fip_image),
             "--output", str(fip_image) + ".usb"],
            label="aml_encrypt_g12a --bootusb",
        )

        self._fip_image = fip_image

    def collect(self, src_dir: Path, config: dict) -> dict:
        """收集 FIP / SD / USB 产物路径供 engine 复制到 target 目录。

        ARTIFACT_NAMES 映射（详见 builder/platforms/amlogic/__init__.py）：
          - (bootloader, fip)     → u-boot.bin       （裸 FIP，pyamlboot 推送用）
          - (bootloader, sd)      → u-boot.bin.sd.bin（SD/eMMC dd 格式，fastboot flash bootloader → mmc1 hw boot0）
          - (bootloader, usb_bl2) → u-boot.bin.usb.bl2（备用：旧式两段 USB 上传 BL2 stub）
          - (bootloader, usb_tpl) → u-boot.bin.usb.tpl（备用：旧式两段 USB 上传 TPL）
        """
        fip_image = self._fip_image
        return {
            "fip":     fip_image,                          # build-fip.sh 直接产出
            "sd":      Path(str(fip_image) + ".sd.bin"),
            "usb_bl2": Path(str(fip_image) + ".usb.bl2"),
            "usb_tpl": Path(str(fip_image) + ".usb.tpl"),
        }
