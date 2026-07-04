"""Allwinner H3 平台构建策略工厂。"""

from builder.docker import DockerRunner
from builder.source import SourceManager


def create_builder(component: str, docker: DockerRunner, source: SourceManager):
    """根据组件名创建对应的 Allwinner H3 构建器。"""
    if component == "kernel":
        from builder.platforms.allwinnerh3.kernel import AllwinnerH3KernelBuilder
        return AllwinnerH3KernelBuilder(docker, source)
    elif component == "bootloader":
        from builder.platforms.allwinnerh3.bootloader import AllwinnerH3BootloaderBuilder
        return AllwinnerH3BootloaderBuilder(docker, source)
    elif component == "rootfs":
        from builder.platforms.allwinnerh3.rootfs import AllwinnerH3RootfsBuilder
        return AllwinnerH3RootfsBuilder(docker, source)
    elif component == "boot":
        from builder.platforms.allwinnerh3.boot import AllwinnerH3BootBuilder
        return AllwinnerH3BootBuilder(docker, source)
    elif component == "image":
        from builder.platforms.allwinnerh3.image import AllwinnerH3ImageBuilder
        return AllwinnerH3ImageBuilder(docker, source)
    elif component == "recovery":
        from builder.platforms.allwinnerh3.recovery import AllwinnerH3RecoveryBuilder
        return AllwinnerH3RecoveryBuilder(docker, source)
    else:
        raise ValueError(f"未知组件: {component}")
