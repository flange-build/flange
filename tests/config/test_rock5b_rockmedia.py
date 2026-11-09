"""ROCK 5B 厂商 GPU 产品的成套切换与隔离契约。"""

import importlib.util

import pytest

from builder.app_spec import load_spec
from builder.config.registry import resolve_config
from builder.paths import PROJECT_ROOT


RUNTIME = PROJECT_ROOT / "components/packages/rockchip-mali-g610/runtime"
GPU_OVERLAY = "rk3588-rock-5b-mali-valhall-compat.dtbo"


@pytest.mark.parametrize("variant", ["debug", "release"])
def test_rockmedia_gpu_stack_and_media_dependencies(variant):
    config = resolve_config("radxa-rock5b", "rockmedia", variant)
    kernel = config["kernel"]
    assert "rk3588_panthor.config" not in kernel["defconfig"]
    assert kernel["config"]["CONFIG_DRM_PANTHOR"] == "n"
    assert kernel["config"]["CONFIG_DRM_PANFROST"] == "n"
    for symbol in (
        "CONFIG_MALI_BIFROST", "CONFIG_MALI_CSF_SUPPORT", "CONFIG_MALI_CSF_INCLUDE_FW",
        "CONFIG_ROCKCHIP_MULTI_RGA", "CONFIG_ROCKCHIP_MPP_SERVICE",
    ):
        assert kernel["config"][symbol] == "y"
    assert GPU_OVERLAY in config["boot"]["overlays"]["enabled"]
    assert {"rockchip-mali-g610", "rockchip-multimedia"} <= set(config["packages"])
    assert {
        "flange-mali-g610", "rkmm-mpp", "rkmm-rga", "rkmm-gst-rockchip", "rkmm-gst-repack",
    } <= set(config["rootfs"]["custom_packages"])
    assert {"clinfo", "mesa-utils", "v4l-utils", "libdrm-tests"} <= set(
        config["rootfs"]["packages"]
    )
    assert "video" in config["rootfs"]["groups"]
    # rootfs 使用 dpkg 安装本地包，所有系统 Depends 必须先进入 APT 基础阶段。
    runtime_dependencies = {item.split()[0] for item in load_spec(RUNTIME).depends}
    assert runtime_dependencies <= set(config["rootfs"]["packages"])


@pytest.mark.parametrize("product", ["default", "desktop", "meizu-e3-bringup"])
@pytest.mark.parametrize("variant", ["debug", "release"])
def test_existing_products_keep_panthor(product, variant):
    config = resolve_config("radxa-rock5b", product, variant)
    assert "rk3588_panthor.config" in config["kernel"]["defconfig"]
    assert "CONFIG_MALI_BIFROST" not in config["kernel"]["config"]
    assert GPU_OVERLAY not in config["boot"]["overlays"]["enabled"]
    assert "rockchip-mali-g610" not in config["packages"]
    assert "flange-mali-g610" not in config["rootfs"]["custom_packages"]


def test_vendor_uses_local_packaging_and_loader_maintenance():
    spec = load_spec(RUNTIME)
    assert spec.app.arch == ["aarch64"]
    assert not spec.packaging.outputs
    assert {"postinst", "postrm", "triggers"} == set(spec.maintainer_scripts)
    for name in ("postinst", "postrm"):
        assert "ldconfig" in spec.maintainer_scripts[name]


def test_corrupt_cached_vendor_input_is_rejected(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("mali_build", RUNTIME / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / module.UPSTREAM_FILE).write_bytes(b"corrupted")

    def unexpected_download(*args, **kwargs):
        pytest.fail("损坏缓存必须拒绝，不能绕过校验继续下载或解包")

    monkeypatch.setattr(module.urllib.request, "urlopen", unexpected_download)
    with pytest.raises(ValueError, match="SHA-256"):
        module.download(tmp_path)
