"""Allwinner A733 平台构建策略工厂。"""

from builder.docker import DockerRunner
from builder.source import SourceManager

# 产物名映射：(组件, collect key) → target 目录下的文件名/目录名
ARTIFACT_NAMES = {
    ("kernel",     "modules"):       "modules",
    ("bootloader", "boot0_sdcard"):   "boot0_sdcard.bin",
    ("bootloader", "boot0_ufs"):      "boot0_ufs.bin",
    ("bootloader", "boot0_spinor"):   "boot0_spinor.bin",
    ("bootloader", "boot_package"):   "boot_package.fex",
    ("boot",       "boot"):          "boot.img",
    ("rootfs",     "rootfs"):        "rootfs.img",
    ("image",      "image"):         "raw.img",
}


def create_builder(component: str, docker: DockerRunner, source: SourceManager):
    """根据组件名创建对应的 Allwinner A733 构建器。"""
    if component == "kernel":
        from builder.platforms.allwinnera733.kernel import AllwinnerA733KernelBuilder
        return AllwinnerA733KernelBuilder(docker, source)
    elif component == "bootloader":
        from builder.platforms.allwinnera733.bootloader import AllwinnerA733BootloaderBuilder
        return AllwinnerA733BootloaderBuilder(docker, source)
    elif component == "rootfs":
        from builder.platforms.allwinnera733.rootfs import AllwinnerA733RootfsBuilder
        return AllwinnerA733RootfsBuilder(docker, source)
    elif component == "boot":
        from builder.platforms.allwinnera733.boot import AllwinnerA733BootBuilder
        return AllwinnerA733BootBuilder(docker, source)
    elif component == "image":
        from builder.platforms.allwinnera733.image import AllwinnerA733ImageBuilder
        return AllwinnerA733ImageBuilder(docker, source)
    else:
        raise ValueError(f"未知组件: {component}")
