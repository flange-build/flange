"""Amlogic 平台构建策略工厂。"""

from builder.docker import DockerRunner
from builder.source import SourceManager

# 产物名映射：(组件, collect key) → target 目录下的文件名/目录名
#
# bootloader 的 FIP、SD 与 USB 格式均由 LibreELEC/amlogic-boot-fip 仓库内
# build-fip.sh 生成；board Makefile 的 aml_encrypt_* --bootmk 一次产齐。
# fastboot 把 SD 格式写入 eMMC boot0 hw 分区（offset 0x200）。
#
# bootloader.usb_bl2 / bootloader.usb_tpl 是 pyamlboot USB 推送 (MaskROM
# 模式) 用的双段镜像，同样由 build-fip.sh 产出；首版可选使用。
ARTIFACT_NAMES = {
    ("kernel",     "dtbos"):     "overlay",
    ("kernel",     "modules"):   "modules",
    # bootloader 产出 4 个变体：
    #   fip      —— 裸 FIP（build-fip.sh 产出），pyamlboot 推 MaskROM 用
    #   sd       —— SD/eMMC dd 格式，fastboot flash bootloader 写入板级
    #               CONFIG_FASTBOOT_FLASH_MMC_DEV 指定的 eMMC hw boot0
    #   usb_bl2/usb_tpl —— 旧式两段 USB 上传（备用，本流程不使用）
    ("bootloader", "fip"):       "u-boot.bin",
    ("bootloader", "sd"):        "u-boot.bin.sd.bin",
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
