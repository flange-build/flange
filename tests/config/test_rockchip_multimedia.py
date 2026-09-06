"""Rockchip 多媒体 package 的迁移边界与板级接入测试。"""

import hashlib
from pathlib import Path

from builder.app_spec import load_spec
from builder.config.registry import resolve_config
from builder.paths import PROJECT_ROOT


PACKAGE_ROOT = PROJECT_ROOT / "components/packages/rockchip-multimedia"
ROCKCHIP_BOARDS = [
    "armsom-cm5-io",
    "neons-core3566-nanob",
    "orangepi-5-plus",
    "orangepi-cm4",
    "orangepi-cm5-tablet",
    "radxa-rock-4d",
    "radxa-rock5b",
    "radxa-rock5c-lite",
    "radxa-zero3w",
    "rp-pro-rk3568-h",
    "tspi-rk3566",
]


def test_patch_set完整迁移且内容固定():
    patch_root = PACKAGE_ROOT / "patches"
    expected_counts = {
        "gstreamer": 4,
        "gst-plugins-base": 22,
        "gst-plugins-good": 12,
        "gst-plugins-bad": 45,
    }
    assert {
        directory.name: len(list(directory.glob("*.patch")))
        for directory in patch_root.iterdir()
        if directory.is_dir()
    } == expected_counts

    digest = hashlib.sha256()
    for path in sorted(patch_root.rglob("*.patch")):
        digest.update(path.relative_to(patch_root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    assert digest.hexdigest() == (
        "76170b166688ed4ef63bb1c06e30736a875011a49cced26d7cd48cbe7c75eec5"
    )


def _unit_specs() -> dict:
    """加载全部单元 App 的规格，按 App 名索引。"""
    return {
        directory.name: load_spec(directory)
        for directory in sorted((PACKAGE_ROOT / "units").iterdir())
        if directory.is_dir()
    }


def test_单元集合声明标准runtime分包且不发布dev包():
    """17 个 deb 的交付契约不变，只是分散到了 4 个产 deb 的单元上。"""
    specs = _unit_specs()
    outputs = [
        name for spec in specs.values() for name in spec.build.deb_outputs
    ]

    assert len(outputs) == 17
    assert all(name.endswith("_arm64.deb") for name in outputs)
    assert all("+flange1_" in name or "flange1_" in name for name in outputs)
    assert not any("-dev_" in name for name in outputs)
    assert {
        name.rsplit("_", 2)[0] for name in outputs
    } >= {
        "libgstreamer1.0-0",
        "gstreamer1.0-tools",
        "gstreamer1.0-plugins-base-apps",
        "libgstreamer-plugins-base1.0-0",
        "libgstreamer-gl1.0-0",
        "gstreamer1.0-plugins-good",
        "libgstreamer-plugins-good1.0-0",
        "gstreamer1.0-plugins-bad-apps",
        "gstreamer1.0-plugins-bad",
        "libgstreamer-plugins-bad1.0-0",
        "rockchip-mpp",
        "librga2",
        "gstreamer1.0-rockchip",
    }


def test_aarch64_Rockchip板显式启用本地多媒体package():
    for board in ROCKCHIP_BOARDS:
        config = resolve_config(board, "default", "release")
        assert config["architecture"]["userspace"] == "aarch64"
        assert "rockchip-multimedia" in config["packages"]
        expected = {
            "rkmm-mpp", "rkmm-rga", "rkmm-gstreamer", "rkmm-gst-base",
            "rkmm-gst-good", "rkmm-gst-bad", "rkmm-gst-rockchip",
            "rkmm-gst-repack", "flange-rockchip-multimedia",
        }
        assert expected <= set(config["rootfs"]["custom_packages"])
        assert expected <= set(config["external_apps"])


def test_旧远程DEB与强制覆盖策略已删除():
    roots = [
        PROJECT_ROOT / "components/config",
        PROJECT_ROOT / "components/platform/rockchip",
        *(
            PROJECT_ROOT / "components/board" / board
            for board in ROCKCHIP_BOARDS
        ),
    ]
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for root in roots
        for path in root.rglob("*.jsonnet")
    )
    assert "rockchip-multimedia-ubuntu" not in text
    assert "multimediaDebs" not in text
    assert "force_overwrite" not in text
    assert "hold_packages" not in text
