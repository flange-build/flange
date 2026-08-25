"""Qualcomm QCS6490 平台构建策略工厂（flange 首个 Qualcomm 平台）。

启动/刷写模型见 components/platform/qualcommqcs6490/qcs6490/config.jsonnet。
各组件构建器在同目录子模块中实现；create_builder 懒加载以便分组落地。
"""

from builder.docker import DockerRunner
from builder.source import SourceManager

# 产物名映射：(组件, collect key) → target 目录下的文件名/目录名。
# 未列出的 key 沿用源文件名（如 kernel 的 image→"Image"、dtb→"<dtb>.dtb"）。
ARTIFACT_NAMES = {
    ("kernel",     "modules"):  "modules",
    ("bootloader", "edk2"):     "edk2-spi-firmware",
    ("boot",       "boot"):     "boot.img",
    ("rootfs",     "rootfs"):   "rootfs.img",
    ("recovery",   "recovery"): "recovery.img",
    ("image",      "image"):    "raw.img",
}


def create_builder(component: str, docker: DockerRunner, source: SourceManager):
    """根据组件名创建对应的 Qualcomm QCS6490 构建器。"""
    if component == "kernel":
        from builder.platforms.qualcommqcs6490.kernel import Qcs6490KernelBuilder
        return Qcs6490KernelBuilder(docker, source)
    elif component == "bootloader":
        from builder.platforms.qualcommqcs6490.bootloader import Qcs6490BootloaderBuilder
        return Qcs6490BootloaderBuilder(docker, source)
    elif component == "rootfs":
        from builder.platforms.qualcommqcs6490.rootfs import Qcs6490RootfsBuilder
        return Qcs6490RootfsBuilder(docker, source)
    elif component == "boot":
        from builder.platforms.qualcommqcs6490.boot import Qcs6490BootBuilder
        return Qcs6490BootBuilder(docker, source)
    elif component == "recovery":
        from builder.platforms.qualcommqcs6490.recovery import Qcs6490RecoveryBuilder
        return Qcs6490RecoveryBuilder(docker, source)
    elif component == "image":
        from builder.platforms.qualcommqcs6490.image import Qcs6490ImageBuilder
        return Qcs6490ImageBuilder(docker, source)
    else:
        raise ValueError(f"未知组件: {component}")
