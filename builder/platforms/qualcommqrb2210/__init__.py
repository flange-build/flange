"""Qualcomm QRB2210 平台构建策略工厂（flange 第二个 Qualcomm 平台）。

Arduino UNO Q（QRB2210/QCM2290，代号 Imola）。启动/刷写模型见
components/platform/qualcommqrb2210/qrb2210/config.py：U-Boot extlinux 世界，
eMMC 固定 vendor GPT，edl-ng 按分区刷。各组件构建器在同目录子模块中实现；
create_builder 懒加载以便分组落地。
"""

from builder.docker import DockerRunner
from builder.source import SourceManager

# 产物名映射：(组件, collect key) → target 目录下的文件名/目录名。
# 未列出的 key 沿用源文件名（如 kernel 的 image→"Image"、dtb→"<dtb>.dtb"）。
ARTIFACT_NAMES = {
    ("kernel",     "modules"):    "modules",
    ("bootloader", "edl"):        "edl-firmware",
    ("boot",       "boot"):       "boot.img",
    ("rootfs",     "rootfs"):     "rootfs.img",
    ("recovery",   "recovery"):   "recovery.img",
    # image 组件不组装整盘 raw.img（vendor 固定 GPT），仅生成 flange rawprogram，
    # 供 edl-ng 按分区刷 boot/rootfs。
    ("image",      "rawprogram"): "flange_rawprogram.xml",
}


def create_builder(component: str, docker: DockerRunner, source: SourceManager):
    """根据组件名创建对应的 Qualcomm QRB2210 构建器。"""
    if component == "kernel":
        from builder.platforms.qualcommqrb2210.kernel import Qrb2210KernelBuilder
        return Qrb2210KernelBuilder(docker, source)
    elif component == "bootloader":
        from builder.platforms.qualcommqrb2210.bootloader import Qrb2210BootloaderBuilder
        return Qrb2210BootloaderBuilder(docker, source)
    elif component == "rootfs":
        from builder.platforms.qualcommqrb2210.rootfs import Qrb2210RootfsBuilder
        return Qrb2210RootfsBuilder(docker, source)
    elif component == "boot":
        from builder.platforms.qualcommqrb2210.boot import Qrb2210BootBuilder
        return Qrb2210BootBuilder(docker, source)
    elif component == "recovery":
        from builder.platforms.qualcommqrb2210.recovery import Qrb2210RecoveryBuilder
        return Qrb2210RecoveryBuilder(docker, source)
    elif component == "image":
        from builder.platforms.qualcommqrb2210.image import Qrb2210ImageBuilder
        return Qrb2210ImageBuilder(docker, source)
    else:
        raise ValueError(f"未知组件: {component}")
