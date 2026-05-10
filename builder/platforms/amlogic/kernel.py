"""Amlogic 内核构建策略。

mainline kernel 6.12 LTS arm64，DT 路径 ``arch/arm64/boot/dts/amlogic/``。
首版聚焦 VIM3L 串口 + SSH + Wi-Fi + BT，所有驱动走 mainline in-tree
（无 OOT 模块），defconfig 直接用 arm64 generic ``defconfig``。
"""

from pathlib import Path
from builder.kernel_base import KernelBuilder


class AmlogicKernelBuilder(KernelBuilder):
    component = "kernel"
    ARCH = "arm64"
    CROSS = "aarch64-linux-gnu-"

    def configure(self, src_dir: Path, config: dict):
        raise NotImplementedError(
            "AmlogicKernelBuilder.configure 待实现（tasks 5.1）：mainline "
            "arm64 generic defconfig + 可选 Amlogic-specific fragment"
        )

    def compile(self, src_dir: Path, config: dict):
        raise NotImplementedError(
            "AmlogicKernelBuilder.compile 待实现（tasks 5.1）：编译 Image + "
            "amlogic/meson-sm1-khadas-vim3l.dtb + modules"
        )

    def collect(self, src_dir: Path, config: dict) -> dict:
        raise NotImplementedError(
            "AmlogicKernelBuilder.collect 待实现（tasks 5.1）：返回 image / "
            "dtb / modules 路径"
        )
