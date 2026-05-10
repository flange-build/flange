"""Amlogic 平台构建策略工厂。"""

from builder.docker import DockerRunner
from builder.source import SourceManager

# 产物名映射：(组件, collect key) → target 目录下的文件名/目录名
#
# bootloader.fip 是 SD/eMMC 可启动的最终镜像，由 LibreELEC/amlogic-boot-fip
# 仓库内 build-fip.sh 拼装 + aml_encrypt_g12a --bootsd 派生。boot0 hw 分区
# 直接 dd 该文件（offset 0x200）。
#
# bootloader.usb_bl2 / bootloader.usb_tpl 是 pyamlboot USB 推送 (MaskROM
# 模式) 用的双段镜像，由 aml_encrypt_g12a --bootusb 派生；首版可选产出。
ARTIFACT_NAMES = {
    ("kernel",     "dtbos"):     "overlay",
    ("kernel",     "modules"):   "modules",
    ("bootloader", "fip"):       "u-boot.bin.sd.bin",
    ("bootloader", "usb_bl2"):   "u-boot.bin.usb.bl2",
    ("bootloader", "usb_tpl"):   "u-boot.bin.usb.tpl",
    ("boot",       "boot"):      "boot.img",
    ("rootfs",     "rootfs"):    "rootfs.img",
    ("recovery",   "recovery"):  "recovery.img",
    ("image",      "image"):     "raw.img",
}


def create_builder(component: str, docker: DockerRunner, source: SourceManager):
    """根据组件名创建对应的 Amlogic 构建器。"""
    if component == "kernel":
        from builder.platforms.amlogic.kernel import AmlogicKernelBuilder
        return AmlogicKernelBuilder(docker, source)
    elif component == "bootloader":
        from builder.platforms.amlogic.bootloader import AmlogicBootloaderBuilder
        return AmlogicBootloaderBuilder(docker, source)
    elif component == "rootfs":
        from builder.platforms.amlogic.rootfs import AmlogicRootfsBuilder
        return AmlogicRootfsBuilder(docker, source)
    elif component == "boot":
        from builder.platforms.amlogic.boot import AmlogicBootBuilder
        return AmlogicBootBuilder(docker, source)
    elif component == "recovery":
        from builder.platforms.amlogic.recovery import AmlogicRecoveryBuilder
        return AmlogicRecoveryBuilder(docker, source)
    elif component == "image":
        from builder.platforms.amlogic.image import AmlogicImageBuilder
        return AmlogicImageBuilder(docker, source)
    else:
        raise ValueError(f"未知组件: {component}")
