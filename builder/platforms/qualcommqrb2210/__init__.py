"""Arduino UNO Q 的 QRB2210 平台契约与懒加载构建工厂。"""

from pathlib import Path

from builder.artifacts import ArtifactSpec

DTBO_MERGE_AT_BUILD = True
EXTRA_DEPENDENCIES = {"boot": ["rootfs"]}
ARTIFACT_NAMES = {
    ("kernel", "modules"): "modules",
    ("kernel", "config"): "config",
    ("kernel", "dtbos"): "overlay",
    ("bootloader", "firmware"): "firmware",
    ("bootloader", "uboot"): "uboot-boot.img",
    ("rootfs", "rootfs"): "rootfs.img",
    ("rootfs", "initrd"): "initrd.img",
    ("rootfs", "userdata"): "userdata.img",
    ("rootfs", "bootaa64"): "bootaa64.efi",
    ("boot", "boot"): "boot.img",
    ("image", "bundle"): "flash-bundle",
}


def required_artifacts(component: str, root: Path, config: dict):
    """完整声明平台专属产物，缺失任何启动输入都禁止缓存命中。"""
    if component == "bootloader":
        loader = config["bootloader"]["firehose_loader"]
        return [
            ArtifactSpec("firmware", root / "firmware", "tree", allow_empty=False),
            ArtifactSpec("firehose", root / "firmware" / loader, allow_empty=False),
            ArtifactSpec("uboot", root / "uboot-boot.img", allow_empty=False),
        ]
    if component == "rootfs":
        return [ArtifactSpec(name, root / filename, allow_empty=False)
                for name, filename in (("rootfs", "rootfs.img"),
                                       ("initrd", "initrd.img"),
                                       ("userdata", "userdata.img"),
                                       ("bootaa64", "bootaa64.efi"),
                                       ("packages", "packages.manifest"))]
    if component == "kernel":
        name = config["kernel"]["device_tree"]["name"]
        outputs = [
            ArtifactSpec("image", root / "Image", allow_empty=False),
            ArtifactSpec("dtb", root / f"{name}.dtb", allow_empty=False),
            ArtifactSpec("modules", root / "modules", "tree", allow_empty=False),
            ArtifactSpec("config", root / "config", allow_empty=False),
        ]
        from builder.dtb_overlay import intree_overlays
        if intree_overlays(config):
            outputs.append(ArtifactSpec("dtbos", root / "overlay", "tree", allow_empty=False))
        return outputs
    if component == "image":
        return [ArtifactSpec("bundle", root / "flash-bundle", "tree", allow_empty=False)]
    return None


def create_builder(component: str, docker, source):
    """只导入所选组件，使配置发现不依赖其他组件的运行环境。"""
    if component == "kernel":
        from .kernel import Qrb2210KernelBuilder
        return Qrb2210KernelBuilder(docker, source)
    if component == "bootloader":
        from .bootloader import Qrb2210BootloaderBuilder
        return Qrb2210BootloaderBuilder(docker, source)
    if component == "boot":
        from .boot import Qrb2210BootBuilder
        return Qrb2210BootBuilder(docker, source)
    if component == "rootfs":
        from .rootfs import Qrb2210RootfsBuilder
        return Qrb2210RootfsBuilder(docker, source)
    if component == "image":
        from .image import Qrb2210ImageBuilder
        return Qrb2210ImageBuilder(docker, source)
    raise ValueError(f"QRB2210 不支持组件: {component}")
