"""Allwinner 平台构建策略工厂。"""

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
    """根据组件名创建对应的 Allwinner 构建器。"""
    if component == "kernel":
        from builder.platforms.allwinner.kernel import AllwinnerKernelBuilder
        return AllwinnerKernelBuilder(docker, source)
    elif component == "bootloader":
        from builder.platforms.allwinner.bootloader import AllwinnerBootloaderBuilder
        return AllwinnerBootloaderBuilder(docker, source)
    elif component == "rootfs":
        from builder.platforms.allwinner.rootfs import AllwinnerRootfsBuilder
        return AllwinnerRootfsBuilder(docker, source)
    elif component == "boot":
        from builder.platforms.allwinner.boot import AllwinnerBootBuilder
        return AllwinnerBootBuilder(docker, source)
    elif component == "image":
        from builder.platforms.allwinner.image import AllwinnerImageBuilder
        return AllwinnerImageBuilder(docker, source)
    else:
        raise ValueError(f"未知组件: {component}")
