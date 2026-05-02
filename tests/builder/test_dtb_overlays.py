"""Device Tree Overlay（设备树覆盖）构建与 extlinux 集成测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from builder.dtb_overlay import (
    all_declared_overlays,
    board_overlays,
    copy_declared_overlays,
    default_overlays,
    dtb_overlays,
    vendor_overlays,
)
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
         default: list[str] | None = None,
         vendor: list[str] | None = None,
         board: list[str] | None = None) -> dict:
    dts = "rk3566-test" if platform == "rockchip" else "sun60i-a733-test"
    boot = {
        "kernel_args": "console=ttyS2,1500000",
        "dtb_overlays": overlays or [],
        "vendor_overlays": vendor or [],
        "board_overlays": board or [],
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


def _prepare_vendor_overlay_target(target_dir: Path, overlays: list[str]) -> None:
    """模拟 device-tree-overlay 组件已构建：target/device-tree-overlay/overlays/"""
    vendor_dir = target_dir / "device-tree-overlay" / "overlays"
    vendor_dir.mkdir(parents=True, exist_ok=True)
    for name in overlays:
        (vendor_dir / name).write_bytes(b"vendor-dtbo")


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


# --- vendor_overlays / all_declared_overlays / cross-source default ---


def test_vendor_overlays_format_violations():
    bad_cases = [
        ("foo", "只能声明 .dtbo 文件"),       # 缺后缀
        ("foo.dts", "只能声明 .dtbo 文件"),   # 错后缀
        ("a/b.dtbo", "只能声明 boot overlay 文件名"),  # 含路径
        (".hidden.dtbo", "只能声明 boot overlay 文件名"),  # 以 . 起头
    ]
    for name, msg in bad_cases:
        cfg = {"boot": {"vendor_overlays": [name]}}
        with pytest.raises((ValueError, TypeError), match=msg):
            vendor_overlays(cfg)


def test_vendor_overlays_must_be_list():
    cfg = {"boot": {"vendor_overlays": "rk3568-i2c1.dtbo"}}
    with pytest.raises(TypeError, match="必须是字符串列表"):
        vendor_overlays(cfg)


def test_vendor_overlays_default_empty():
    cfg = {"boot": {}}
    assert vendor_overlays(cfg) == []
    assert dtb_overlays(cfg) == []
    assert all_declared_overlays(cfg) == []


def test_all_declared_overlays_returns_union_in_order():
    cfg = _cfg(
        "rockchip",
        overlays=["my-local.dtbo"],
        vendor=["radxa-zero3-a.dtbo", "rk3568-i2c1.dtbo"],
    )
    assert all_declared_overlays(cfg) == [
        "my-local.dtbo",
        "radxa-zero3-a.dtbo",
        "rk3568-i2c1.dtbo",
    ]


def test_all_declared_overlays_collision_raises():
    cfg = _cfg(
        "rockchip",
        overlays=["foo.dtbo", "bar.dtbo"],
        vendor=["foo.dtbo", "qux.dtbo"],
    )
    with pytest.raises(ValueError, match="重名.*foo.dtbo"):
        all_declared_overlays(cfg)


def test_default_overlays_can_reference_vendor_source():
    cfg = _cfg(
        "rockchip",
        overlays=["local.dtbo"],
        vendor=["rk3568-i2c1.dtbo"],
        default=["rk3568-i2c1.dtbo"],   # 来自 vendor
    )
    assert default_overlays(cfg) == ["rk3568-i2c1.dtbo"]


def test_default_overlays_unknown_lists_both_candidates():
    cfg = _cfg(
        "rockchip",
        overlays=["local.dtbo"],
        vendor=["rk3568-i2c1.dtbo"],
        default=["missing.dtbo"],
    )
    with pytest.raises(ValueError) as excinfo:
        default_overlays(cfg)
    msg = str(excinfo.value)
    assert "missing.dtbo" in msg
    assert "local.dtbo" in msg          # 列出 dtb_overlays 候选
    assert "rk3568-i2c1.dtbo" in msg    # 列出 vendor_overlays 候选


def test_rockchip_boot_copies_both_intree_and_vendor_overlays(tmp_path):
    target_dir = tmp_path / "target"
    _prepare_kernel_target(target_dir, "rockchip", ["my-local.dtbo"])
    _prepare_vendor_overlay_target(target_dir, ["rk3568-i2c1.dtbo"])

    builder = RockchipBootBuilder(docker=FakeDocker(), source=None)
    builder.cache = FakeCache(target_dir)

    builder.compile(None, _cfg(
        "rockchip",
        overlays=["my-local.dtbo"],
        vendor=["rk3568-i2c1.dtbo"],
        default=["rk3568-i2c1.dtbo"],
    ))

    overlay_dir = (
        builder._work_dir / "staging" / "dtbs" / "rockchip" / "overlay"
    )
    assert (overlay_dir / "my-local.dtbo").exists()
    assert (overlay_dir / "rk3568-i2c1.dtbo").exists()
    assert (overlay_dir / "rk3568-i2c1.dtbo").read_bytes() == b"vendor-dtbo"


def test_a733_boot_copies_both_intree_and_vendor_overlays(tmp_path):
    target_dir = tmp_path / "target"
    _prepare_kernel_target(target_dir, "allwinnera733", ["my-local.dtbo"])
    _prepare_vendor_overlay_target(target_dir, ["a733-foo.dtbo"])

    builder = AllwinnerA733BootBuilder(docker=FakeDocker(), source=None)
    builder.cache = FakeCache(target_dir)

    builder.compile(None, _cfg(
        "allwinnera733",
        overlays=["my-local.dtbo"],
        vendor=["a733-foo.dtbo"],
        default=["a733-foo.dtbo"],
    ))

    overlay_dir = (
        builder._work_dir / "staging" / "dtbs" / "allwinner" / "overlay"
    )
    assert (overlay_dir / "my-local.dtbo").exists()
    assert (overlay_dir / "a733-foo.dtbo").exists()


def test_rockchip_boot_basename_collision_raises(tmp_path):
    target_dir = tmp_path / "target"
    # 两源都声明 foo.dtbo
    _prepare_kernel_target(target_dir, "rockchip", ["foo.dtbo"])
    _prepare_vendor_overlay_target(target_dir, ["foo.dtbo"])

    builder = RockchipBootBuilder(docker=FakeDocker(), source=None)
    builder.cache = FakeCache(target_dir)

    with pytest.raises(ValueError, match="撞名.*foo.dtbo"):
        builder.compile(None, _cfg(
            "rockchip",
            overlays=["foo.dtbo"],
            vendor=["foo.dtbo"],
        ))


# --- board_overlays（板私有源）---


def test_board_overlays_default_empty():
    cfg = {"boot": {}}
    assert board_overlays(cfg) == []


def test_board_overlays_format_violations():
    bad_cases = [
        ("foo", "只能声明 .dtbo 文件"),
        ("a/b.dtbo", "只能声明 boot overlay 文件名"),
        (".hidden.dtbo", "只能声明 boot overlay 文件名"),
    ]
    for name, msg in bad_cases:
        cfg = {"boot": {"board_overlays": [name]}}
        with pytest.raises((ValueError, TypeError), match=msg):
            board_overlays(cfg)


def test_all_declared_overlays_merges_three_sources_in_order():
    cfg = _cfg(
        "allwinnera733",
        overlays=["intree.dtbo"],
        vendor=["vendor.dtbo"],
        board=["board.dtbo"],
    )
    assert all_declared_overlays(cfg) == [
        "intree.dtbo",
        "vendor.dtbo",
        "board.dtbo",
    ]


def test_all_declared_overlays_intree_vs_board_collision():
    cfg = _cfg(
        "allwinnera733",
        overlays=["foo.dtbo"],
        board=["foo.dtbo"],
    )
    with pytest.raises(ValueError,
                       match="dtb_overlays.*board_overlays.*foo.dtbo"):
        all_declared_overlays(cfg)


def test_all_declared_overlays_vendor_vs_board_collision():
    cfg = _cfg(
        "allwinnera733",
        vendor=["foo.dtbo"],
        board=["foo.dtbo"],
    )
    with pytest.raises(ValueError,
                       match="vendor_overlays.*board_overlays.*foo.dtbo"):
        all_declared_overlays(cfg)


def test_default_overlays_can_reference_board_source():
    cfg = _cfg(
        "allwinnera733",
        board=["my-display.dtbo"],
        default=["my-display.dtbo"],
    )
    assert default_overlays(cfg) == ["my-display.dtbo"]


def test_default_overlays_unknown_lists_three_candidates():
    cfg = _cfg(
        "allwinnera733",
        overlays=["intree.dtbo"],
        vendor=["vendor.dtbo"],
        board=["my-display.dtbo"],
        default=["missing.dtbo"],
    )
    with pytest.raises(ValueError) as excinfo:
        default_overlays(cfg)
    msg = str(excinfo.value)
    assert "missing.dtbo" in msg
    assert "intree.dtbo" in msg
    assert "vendor.dtbo" in msg
    assert "my-display.dtbo" in msg
    assert "board_overlays" in msg


def test_a733_boot_copies_board_overlay_to_dtbs_layout(tmp_path):
    """board overlay 与 vendor 共用 target/device-tree-overlay/overlays/ 产物目录。"""
    target_dir = tmp_path / "target"
    _prepare_kernel_target(target_dir, "allwinnera733", [])
    # board overlay 由 OverlaysBuilder 与 vendor overlay 一同写到该目录
    _prepare_vendor_overlay_target(
        target_dir, ["my-display.dtbo"]
    )

    builder = AllwinnerA733BootBuilder(docker=FakeDocker(), source=None)
    builder.cache = FakeCache(target_dir)

    builder.compile(None, _cfg(
        "allwinnera733",
        board=["my-display.dtbo"],
        default=["my-display.dtbo"],
    ))

    overlay_dir = (
        builder._work_dir / "staging" / "dtbs" / "allwinner" / "overlay"
    )
    assert (overlay_dir / "my-display.dtbo").exists()


def test_rockchip_boot_copies_board_overlay_to_dtbs_layout(tmp_path):
    target_dir = tmp_path / "target"
    _prepare_kernel_target(target_dir, "rockchip", [])
    _prepare_vendor_overlay_target(
        target_dir, ["my-display.dtbo"]
    )

    builder = RockchipBootBuilder(docker=FakeDocker(), source=None)
    builder.cache = FakeCache(target_dir)

    builder.compile(None, _cfg(
        "rockchip",
        board=["my-display.dtbo"],
        default=["my-display.dtbo"],
    ))

    overlay_dir = (
        builder._work_dir / "staging" / "dtbs" / "rockchip" / "overlay"
    )
    assert (overlay_dir / "my-display.dtbo").exists()


def test_a733_boot_basename_collision_vendor_vs_board(tmp_path):
    """vendor 与 board 在 config 期就被 all_declared_overlays 拦截。"""
    target_dir = tmp_path / "target"
    _prepare_kernel_target(target_dir, "allwinnera733", [])

    builder = AllwinnerA733BootBuilder(docker=FakeDocker(), source=None)
    builder.cache = FakeCache(target_dir)

    cfg = _cfg(
        "allwinnera733",
        vendor=["foo.dtbo"],
        board=["foo.dtbo"],
        default=["foo.dtbo"],
    )
    # 必须在 _build_extlinux_conf -> default_overlays -> all_declared_overlays
    # 路径上拦截
    with pytest.raises(ValueError, match="重名.*foo.dtbo"):
        builder._build_extlinux_conf(cfg, "sunxi.dtb")


def test_copy_declared_overlays_collision_raises(tmp_path):
    src_a = tmp_path / "a"
    src_b = tmp_path / "b"
    dst = tmp_path / "dst"
    src_a.mkdir()
    src_b.mkdir()
    (src_a / "foo.dtbo").write_bytes(b"A")
    (src_b / "foo.dtbo").write_bytes(b"B")

    copy_declared_overlays(src_a, dst, ["foo.dtbo"])
    assert (dst / "foo.dtbo").read_bytes() == b"A"

    with pytest.raises(ValueError, match="撞名.*foo.dtbo"):
        copy_declared_overlays(src_b, dst, ["foo.dtbo"])
    # 原文件没被覆盖
    assert (dst / "foo.dtbo").read_bytes() == b"A"
