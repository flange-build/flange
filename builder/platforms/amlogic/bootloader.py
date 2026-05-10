"""Amlogic Bootloader 构建策略。

mainline u-boot 编译产出 ``u-boot.bin``，再通过 LibreELEC/amlogic-boot-fip
仓库的 ``build-fip.sh <board_dir> <u-boot.bin> <out>`` 拼装 FIP（含 BL2
SIG / BL30+BL301 加密 / BL31 加密 / BL33 加密 / DDR fw 嵌入），最后用
仓库内 ``aml_encrypt_g12a --bootsd`` 派生 SD/eMMC 可启动镜像
``u-boot.bin.sd.bin``，可选派生 USB BL2/TPL（pyamlboot 推送用）。

字段分层：
- SoC 层 bootloader.fip_tool / fip_family_inc — 工具与 family include script
- board 层 bootloader.fip_board_dir — amlogic-boot-fip 仓库内 board 子目录名
"""

from pathlib import Path
from builder.base import ComponentBuilder


class AmlogicBootloaderBuilder(ComponentBuilder):
    component = "bootloader"
    ARCH = "arm64"
    CROSS = "aarch64-linux-gnu-"

    def configure(self, src_dir: Path, config: dict):
        raise NotImplementedError(
            "AmlogicBootloaderBuilder.configure 待实现（tasks 4.3）：合并 "
            "khadas-vim3l_defconfig + flange-fastboot.config fragment"
        )

    def compile(self, src_dir: Path, config: dict):
        raise NotImplementedError(
            "AmlogicBootloaderBuilder.compile 待实现（tasks 4.3-4.5）：编译 "
            "u-boot → build-fip.sh 拼装 → aml_encrypt_g12a --bootsd 派生"
        )

    def collect(self, src_dir: Path, config: dict) -> dict:
        raise NotImplementedError(
            "AmlogicBootloaderBuilder.collect 待实现（tasks 4.6）：返回 "
            "fip / usb_bl2 / usb_tpl 三个产物路径"
        )
