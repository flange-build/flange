"""Amlogic Rootfs 构建策略。

复用 RootfsBuilder 基类的两阶段缓存（base / customize）、overlay、
firmware 等通用能力。Amlogic VIM3L 的特殊性集中在 rootfs.+packages
（``firmware-brcm80211`` 提供 WiFi/BT 通用固件）与 rootfs.+extra_firmware
（fenix AP6398S 板级 NVRAM + BT patchram 覆盖），这些字段由 board config
注入，rootfs builder 自身不感知 board 差异。
"""

from pathlib import Path
from builder.rootfs import RootfsBuilder


class AmlogicRootfsBuilder(RootfsBuilder):
    component = "rootfs"

    def build(self, config: dict) -> dict:
        """rootfs 无需克隆源码仓库。"""
        self.compile(None, config)
        return self.collect(None, config)

    def configure(self, src_dir: Path, config: dict):
        pass

    def compile(self, src_dir: Path, config: dict):
        raise NotImplementedError(
            "AmlogicRootfsBuilder.compile 待实现（tasks 5.3）：两阶段构建 "
            "(base/customize)，含 +packages firmware-brcm80211 与 fenix "
            "AP6398S +extra_firmware 覆盖"
        )

    def collect(self, src_dir: Path, config: dict) -> dict:
        raise NotImplementedError(
            "AmlogicRootfsBuilder.collect 待实现（tasks 5.3）"
        )
