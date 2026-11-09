"""NVIDIA Tegra186（Jetson TX2）平台契约与懒加载构建工厂。

启动链：MB1 → MB2 → cboot → U-Boot（`kernel` 分区）→ APP 分区 `/boot/extlinux`。
cboot 从 `kernel-dtb` 分区读取内核 DTB 并经 U-Boot 交给内核，extlinux 不写 FDT，
因此没有运行期加载 overlay 的位置，DTBO 只能在构建期合并。
"""

from pathlib import Path

from builder.artifacts import ArtifactSpec

DTBO_MERGE_AT_BUILD = True
ARTIFACT_NAMES = {
    ("kernel", "modules"): "modules",
    ("kernel", "config"): "config",
    ("bootloader", "tegraflash"): "tegraflash",
    ("boot", "kernel_dtb"): "kernel-dtb.dtb",
    ("rootfs", "rootfs"): "rootfs.img",
    ("image", "bundle"): "tegraflash-bundle",
}


def required_artifacts(component: str, root: Path, config: dict):
    """声明平台专属产物；启动链或刷写包缺任何文件都禁止缓存命中。"""
    if component == "kernel":
        name = config["kernel"]["device_tree"]["name"]
        outputs = [
            ArtifactSpec("image", root / "Image", allow_empty=False),
            ArtifactSpec("dtb", root / f"{name}.dtb", allow_empty=False),
            ArtifactSpec("modules", root / "modules", "tree", allow_empty=False),
            ArtifactSpec("config", root / "config", allow_empty=False),
        ]
        from builder.config.canonical import kernel_headers_package
        if kernel_headers_package(config):
            outputs.append(ArtifactSpec("headers", root / "headers", "tree", allow_empty=False))
        return outputs
    if component == "bootloader":
        tree = root / "tegraflash"
        return [
            ArtifactSpec("tegraflash", tree, "tree", allow_empty=False),
            ArtifactSpec("tegraflash_py", tree / "tegraflash.py", allow_empty=False),
            ArtifactSpec("uboot", tree / "boot.img", allow_empty=False),
            ArtifactSpec("bootctrl", tree / "kernel_bootctrl.bin", allow_empty=False),
        ]
    if component == "boot":
        return [ArtifactSpec("kernel_dtb", root / "kernel-dtb.dtb", allow_empty=False)]
    if component == "image":
        bundle = root / "tegraflash-bundle"
        return [
            ArtifactSpec("bundle", bundle, "tree", allow_empty=False),
            ArtifactSpec("manifest", bundle / "manifest.json", allow_empty=False),
        ]
    return None


def create_builder(component: str, docker, source):
    """只导入所选组件，配置发现与计划不依赖其他组件的运行环境。"""
    if component == "kernel":
        from builder.platforms.nvidiategra186.kernel import Tegra186KernelBuilder
        return Tegra186KernelBuilder(docker, source)
    if component == "bootloader":
        from builder.platforms.nvidiategra186.bootloader import Tegra186BootloaderBuilder
        return Tegra186BootloaderBuilder(docker, source)
    if component == "boot":
        from builder.platforms.nvidiategra186.boot import Tegra186BootBuilder
        return Tegra186BootBuilder(docker, source)
    if component == "rootfs":
        from builder.platforms.nvidiategra186.rootfs import Tegra186RootfsBuilder
        return Tegra186RootfsBuilder(docker, source)
    if component == "image":
        from builder.platforms.nvidiategra186.image import Tegra186ImageBuilder
        return Tegra186ImageBuilder(docker, source)
    raise ValueError(f"Tegra186 不支持组件: {component}")
