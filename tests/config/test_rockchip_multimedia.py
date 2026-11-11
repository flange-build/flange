"""Rockchip 多媒体 package 的运行包边界与板级接入测试。"""

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


def _unit_specs() -> dict:
    """加载全部单元 App 的规格，按 App 名索引。"""
    return {
        directory.name: load_spec(directory)
        for directory in sorted((PACKAGE_ROOT / "units").iterdir())
        if directory.is_dir()
    }


def test_单元集合声明标准runtime分包且不发布dev包():
    """运行包覆盖多媒体栈，不把开发包装入目标 rootfs。"""
    specs = _unit_specs()
    outputs = [
        name for spec in specs.values() for name in spec.build.deb_outputs
    ]

    assert outputs and len(outputs) == len(set(outputs))
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
