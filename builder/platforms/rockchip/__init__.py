"""Rockchip 平台构建策略工厂。"""

from builder.docker import DockerRunner
from builder.source import SourceManager


def create_builder(component: str, docker: DockerRunner, source: SourceManager):
    """根据组件名创建对应的 Rockchip 构建器。"""
    if component == "kernel":
        from builder.platforms.rockchip.kernel import RockchipKernelBuilder
        return RockchipKernelBuilder(docker, source)
    elif component == "bootloader":
        from builder.platforms.rockchip.bootloader import RockchipBootloaderBuilder
        return RockchipBootloaderBuilder(docker, source)
    elif component == "rootfs":
        from builder.platforms.rockchip.rootfs import RockchipRootfsBuilder
        return RockchipRootfsBuilder(docker, source)
    elif component in ("boot", "image"):
        from builder.platforms.rockchip.image import RockchipImageBuilder
        return RockchipImageBuilder(docker, source)
    else:
        raise ValueError(f"未知组件: {component}")
