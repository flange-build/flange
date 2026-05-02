"""Device Tree Overlay（设备树覆盖）构建与 extlinux 集成测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from builder.platforms.allwinnera733 import ARTIFACT_NAMES as A733_ARTIFACT_NAMES
from builder.platforms.allwinnera733.boot import AllwinnerA733BootBuilder
from builder.platforms.allwinnera733.kernel import AllwinnerA733KernelBuilder
from builder.platforms.rockchip.boot import RockchipBootBuilder
from builder.platforms.rockchip.kernel import RockchipKernelBuilder


class RecordingRockchipKernelBuilder(RockchipKernelBuilder):
    """记录 make 调用，避免执行真实内核编译。"""

    def __init__(self):
        super().__init__(docker=None, source=None)
        self.make_calls: list[list[str]] = []

    def make(self, src_dir: Path, targets: list, **kwargs):
        self.make_calls.append(list(targets))


class RecordingA733KernelBuilder(AllwinnerA733KernelBuilder):
    """记录 make 调用，避免执行真实内核编译。"""

    def __init__(self):
        super().__init__(docker=None, source=None)
        self.make_calls: list[list[str]] = []

    def make(self, src_dir: Path, targets: list, **kwargs):
        self.make_calls.append(list(targets))


class FakeDocker:
    """记录 docker 命令，避免运行 truncate/mke2fs。"""

    def __init__(self):
        self.commands: list[list[str]] = []

    def run(self, cmd: list[str], **kwargs):
        self.commands.append(list(cmd))


class FakeCache:
    def __init__(self, target_dir: Path):
        self.target_dir = target_dir


def _cfg(platform: str, *, overlays: list[str] | None = None,
         default: list[str] | None = None) -> dict:
    dts = "rk3566-test" if platform == "rockchip" else "sun60i-a733-test"
    boot = {
        "kernel_args": "console=ttyS2,1500000",
        "dtb_overlays": overlays or [],
        "default_overlays": default or [],
    }
    if platform == "allwinnera733":
        boot["dtb_filename"] = "sunxi.dtb"
        boot["root_partuuid"] = "614e0000-0000-4000-8000-000000000001"
    return {
        "platform": platform,
        "soc": "rk3566" if platform == "rockchip" else "a733",
        "board": "test",
        "kernel": {
            "dts": dts,
            "dts_dir": "rockchip" if platform == "rockchip" else "allwinner",
        },
        "boot": boot,
        "recovery": {"enabled": True},
        "partitions": {
            "entries": [
                {"name": "boot", "size": "0x2000"},
            ],
        },
    }


def _prepare_kernel_target(target_dir: Path, platform: str,
                           overlays: list[str]) -> str:
    kernel_dir = target_dir / "kernel"
    kernel_dir.mkdir(parents=True)
    (kernel_dir / "Image").write_bytes(b"image")
    dtb_name = "rk3566-test.dtb" if platform == "rockchip" else "sun60i-a733-test.dtb"
    (kernel_dir / dtb_name).write_bytes(b"dtb")
    overlay_dir = kernel_dir / "overlay"
    overlay_dir.mkdir()
    for name in overlays:
        (overlay_dir / name).write_bytes(b"dtbo")
    return dtb_name


def test_default_overlay_must_be_declared_in_dtb_overlays():
    builder = RockchipBootBuilder(docker=None, source=None)
    config = _cfg("rockchip", overlays=[], default=["missing.dtbo"])

    with pytest.raises(ValueError, match="missing.dtbo"):
        builder._build_extlinux_conf(config, "rk3566-test.dtb")


def test_rockchip_extlinux_renders_multiple_overlays_in_order():
    builder = RockchipBootBuilder(docker=None, source=None)
    config = _cfg(
        "rockchip",
        overlays=["i2c1.dtbo", "spi1.dtbo"],
        default=["i2c1.dtbo", "spi1.dtbo"],
    )

    text = builder._build_extlinux_conf(config, "rk3566-test.dtb")

    assert (
        "  fdtoverlays "
        "/dtbs/rockchip/overlay/i2c1.dtbo "
        "/dtbs/rockchip/overlay/spi1.dtbo"
    ) in text
    assert "  kernel /extlinux/Image" in text
    assert "  fdt /dtbs/rockchip/rk3566-test.dtb" in text


def test_rockchip_recovery_extlinux_uses_same_default_overlays():
    builder = RockchipBootBuilder(docker=None, source=None)
    config = _cfg(
        "rockchip",
        overlays=["i2c1.dtbo", "display.dtbo"],
        default=["i2c1.dtbo", "display.dtbo"],
    )

    text = builder._build_recovery_extlinux_conf(config, "rk3566-test.dtb")

    assert (
        "  fdtoverlays "
        "/dtbs/rockchip/overlay/i2c1.dtbo "
        "/dtbs/rockchip/overlay/display.dtbo"
    ) in text


def test_a733_extlinux_renders_multiple_overlays_in_order():
    builder = AllwinnerA733BootBuilder(docker=None, source=None)
    config = _cfg(
        "allwinnera733",
        overlays=["i2c1.dtbo", "spi1.dtbo"],
        default=["i2c1.dtbo", "spi1.dtbo"],
    )

    text = builder._build_extlinux_conf(config, "sunxi.dtb")

    assert (
        "  fdtoverlays "
        "/dtbs/allwinner/overlay/i2c1.dtbo "
        "/dtbs/allwinner/overlay/spi1.dtbo"
    ) in text
    assert "  devicetree /dtbs/allwinner/sunxi.dtb" in text


def test_a733_recovery_extlinux_uses_same_default_overlays():
    builder = AllwinnerA733BootBuilder(docker=None, source=None)
    config = _cfg(
        "allwinnera733",
        overlays=["i2c1.dtbo"],
        default=["i2c1.dtbo"],
    )

    text = builder._build_recovery_extlinux_conf(config, "sunxi.dtb")

    assert "  fdtoverlays /dtbs/allwinner/overlay/i2c1.dtbo" in text


def test_rockchip_kernel_compile_adds_overlay_targets(tmp_path):
    builder = RecordingRockchipKernelBuilder()
    config = _cfg("rockchip", overlays=["i2c1.dtbo", "spi1.dtbo"])

    builder.compile(tmp_path, config)

    assert "rockchip/overlay/i2c1.dtbo" in builder.make_calls[0]
    assert "rockchip/overlay/spi1.dtbo" in builder.make_calls[0]


def test_a733_kernel_compile_adds_overlay_targets(tmp_path):
    builder = RecordingA733KernelBuilder()
    config = _cfg("allwinnera733", overlays=["i2c1.dtbo", "spi1.dtbo"])

    builder.compile(tmp_path, config)

    assert "allwinner/overlay/i2c1.dtbo" in builder.make_calls[0]
    assert "allwinner/overlay/spi1.dtbo" in builder.make_calls[0]


def test_rockchip_kernel_collect_requires_declared_overlay(tmp_path):
    builder = RockchipKernelBuilder(docker=None, source=None)
    config = _cfg("rockchip", overlays=["i2c1.dtbo"])
    dts_dir = tmp_path / "arch" / "arm64" / "boot" / "dts" / "rockchip"
    dts_dir.mkdir(parents=True)
    (tmp_path / "arch" / "arm64" / "boot").mkdir(parents=True, exist_ok=True)
    (tmp_path / "arch" / "arm64" / "boot" / "Image").write_bytes(b"image")
    (dts_dir / "rk3566-test.dtb").write_bytes(b"dtb")

    with pytest.raises(FileNotFoundError, match="i2c1.dtbo"):
        builder.collect(tmp_path, config)


def test_a733_kernel_collect_returns_dtbos(tmp_path):
    builder = AllwinnerA733KernelBuilder(docker=None, source=None)
    config = _cfg("allwinnera733", overlays=["i2c1.dtbo"])
    dts_dir = tmp_path / "arch" / "arm64" / "boot" / "dts" / "allwinner"
    overlay_dir = dts_dir / "overlay"
    overlay_dir.mkdir(parents=True)
    (tmp_path / "arch" / "arm64" / "boot").mkdir(parents=True, exist_ok=True)
    (tmp_path / "arch" / "arm64" / "boot" / "Image").write_bytes(b"image")
    (dts_dir / "sun60i-a733-test.dtb").write_bytes(b"dtb")
    (overlay_dir / "i2c1.dtbo").write_bytes(b"dtbo")

    outputs = builder.collect(tmp_path, config)

    assert outputs["dtbos"] == overlay_dir


def test_rockchip_boot_copies_declared_overlay_to_dtbs_layout(tmp_path):
    target_dir = tmp_path / "target"
    _prepare_kernel_target(target_dir, "rockchip", ["i2c1.dtbo"])
    builder = RockchipBootBuilder(docker=FakeDocker(), source=None)
    builder.cache = FakeCache(target_dir)

    builder.compile(None, _cfg("rockchip", overlays=["i2c1.dtbo"], default=["i2c1.dtbo"]))

    assert (
        builder._work_dir
        / "staging"
        / "dtbs"
        / "rockchip"
        / "overlay"
        / "i2c1.dtbo"
    ).exists()
    assert (builder._work_dir / "staging" / "extlinux" / "Image").exists()
    assert (
        builder._work_dir
        / "staging"
        / "dtbs"
        / "rockchip"
        / "rk3566-test.dtb"
    ).exists()


def test_a733_boot_copies_declared_overlay_to_dtbs_layout(tmp_path):
    target_dir = tmp_path / "target"
    _prepare_kernel_target(target_dir, "allwinnera733", ["i2c1.dtbo"])
    builder = AllwinnerA733BootBuilder(docker=FakeDocker(), source=None)
    builder.cache = FakeCache(target_dir)

    builder.compile(
        None,
        _cfg("allwinnera733", overlays=["i2c1.dtbo"], default=["i2c1.dtbo"]),
    )

    assert (
        builder._work_dir
        / "staging"
        / "dtbs"
        / "allwinner"
        / "overlay"
        / "i2c1.dtbo"
    ).exists()
    assert (builder._work_dir / "staging" / "extlinux" / "Image").exists()
    assert (
        builder._work_dir
        / "staging"
        / "dtbs"
        / "allwinner"
        / "sunxi.dtb"
    ).exists()


def test_a733_artifact_names_collect_kernel_dtbos():
    assert A733_ARTIFACT_NAMES[("kernel", "dtbos")] == "overlay"


@pytest.mark.parametrize(
    "patch_path",
    [
        Path("components/platform/rockchip/patches/bootloader/0002-select-flange-recovery-extlinux-conf.patch"),
        Path("components/platform/allwinnera733/patches/bootloader/0001-select-flange-recovery-extlinux-conf.patch"),
    ],
)
def test_uboot_patches_define_fdtoverlay_addr_r(patch_path):
    assert "fdtoverlay_addr_r=" in patch_path.read_text()
