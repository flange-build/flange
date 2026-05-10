"""Amlogic 完整镜像构建策略。

产物：raw.img — 完整 user area GPT 镜像，含 env / boot / recovery / rootfs
四个 GPT 分区数据。

注意：u-boot.bin.sd.bin 不写在 raw.img 内 —— Amlogic eMMC 启动靠硬件
boot0 hw 分区（offset 0x200），由 flash 阶段单独通过 fastboot 写入
``bootloader`` 目标（u-boot.bin.sd.bin）；user area GPT 仅承载内容
分区。SD 卡启动模式（首版 Non-Goal）下需把 u-boot.bin.sd.bin 直接
dd 到 SD 的 offset 0x200，但本变更不涉及。
"""

from pathlib import Path
from builder.base import ComponentBuilder


class AmlogicImageBuilder(ComponentBuilder):
    component = "image"

    def build(self, config: dict) -> dict:
        """image 无需克隆源码仓库。"""
        self.compile(None, config)
        return self.collect(None, config)

    def configure(self, src_dir: Path, config: dict):
        pass  # image 无 configure 步骤

    def compile(self, src_dir: Path, config: dict):
        raise NotImplementedError(
            "AmlogicImageBuilder.compile 待实现（tasks 5.5）：拼装 user area "
            "GPT raw.img；不含 boot0 hw 分区"
        )

    def collect(self, src_dir: Path, config: dict) -> dict:
        raise NotImplementedError(
            "AmlogicImageBuilder.collect 待实现（tasks 5.5）"
        )
