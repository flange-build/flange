"""Rockchip 平台构建策略工厂。"""

from builder.docker import DockerRunner
from builder.source import SourceManager

# 产物名映射：(组件, collect key) → target 目录下的文件名/目录名
ARTIFACT_NAMES = {
    ("kernel", "fit_boot"): "boot.img",
    ("kernel", "dtbos"): "overlay",
    ("kernel", "modules"): "modules",
    ("bootloader", "bootloader"): "u-boot.itb",
    ("bootloader", "idbloader"): "idbloader.img",
    ("bootloader", "miniloader"): "miniloader.bin",
    ("boot", "boot"): "boot.img",
    ("rootfs", "rootfs"): "rootfs.img",
    ("rootfs", "ubi"): "rootfs.ubi",
    ("recovery", "recovery"): "recovery.img",
    ("amp", "amp"): "amp.img",
    ("image", "image"): "raw.img",
    ("image", "bundle"): "mtd-bundle.json",
}


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
    elif component == "boot":
        from builder.platforms.rockchip.boot import RockchipBootBuilder

        return RockchipBootBuilder(docker, source)
    elif component == "recovery":
        from builder.platforms.rockchip.recovery import RockchipRecoveryBuilder

        return RockchipRecoveryBuilder(docker, source)
    elif component == "image":
        from builder.platforms.rockchip.image import RockchipImageBuilder

        return RockchipImageBuilder(docker, source)
    elif component == "amp":
        from builder.platforms.rockchip.amp import RockchipAmpBuilder

        return RockchipAmpBuilder(docker, source)
    else:
        raise ValueError(f"未知组件: {component}")
