"""QCS6490 Jsonnet 代表路径的 canonical 语义测试。"""

import pytest

from builder.config.jsonnet import JsonnetConfigLoader
from builder.config.validate import validate_canonical_config
from builder.paths import PROJECT_ROOT


@pytest.mark.parametrize("product", ["default", "meizu-e3-bringup"])
@pytest.mark.parametrize("variant", ["debug", "release"])
def test_q6a求值为canonical配置(product, variant):
    config = JsonnetConfigLoader(PROJECT_ROOT).evaluate_board(
        "radxa-dragon-q6a", product, variant)

    validate_canonical_config(config)
    assert config["kernel"]["source"] == {"name": "linux-qcs6490"}
    assert config["kernel"]["device_tree"]["directory"] == "qcom"
    assert config["kernel"]["device_tree"]["name"] == (
        "qcs6490-radxa-dragon-q6a")
    assert "enable_configs" not in config["kernel"]
    assert "disable_configs" not in config["kernel"]
    assert all(not item.startswith("CONFIG_")
               for item in config["kernel"]["defconfig"])
    assert config["kernel"]["config"]["CONFIG_MODULE_SIG_FORCE"] == "n"
    assert ("mesa-utils" in config["rootfs"]["packages"]) == (
        variant == "debug")

    if product == "meizu-e3-bringup":
        assert config["kernel"]["device_tree"]["build_overlays"]
    else:
        assert "build_overlays" not in config["kernel"]["device_tree"]


@pytest.mark.parametrize("variant", ["debug", "release"])
def test_q8b不再混用raw_defconfig与enable_disable(variant):
    config = JsonnetConfigLoader(PROJECT_ROOT).evaluate_board(
        "radxa-dragon-q8b", "default", variant)

    validate_canonical_config(config)
    assert config["kernel"]["defconfig"] == ["radxa_qcom_7_0_defconfig"]
    assert config["kernel"]["config"]["CONFIG_DRM_MSM"] == "m"
    assert config["kernel"]["config"]["CONFIG_DRM_AMDGPU"] == "n"
    assert config["kernel"]["device_tree"] == {
        "directory": "qcom",
        "name": "sc8280xp-radxa-dragon-q8b",
    }
    assert set(config["kernel"]).isdisjoint({
        "enable_configs", "disable_configs", "dts", "dtb", "dts_dir",
    })


def test_vim3l板层与soc层共用kernel_config且保留binder():
    config = JsonnetConfigLoader(PROJECT_ROOT).evaluate_board(
        "khadas-vim3l", "default", "release")

    validate_canonical_config(config)
    assert config["kernel"]["config"] == {
        "CONFIG_ANDROID_BINDERFS": "y",
        "CONFIG_ANDROID_BINDER_IPC": "y",
        "CONFIG_DRM_GUD": "y",
        "CONFIG_NET": "y",
        "CONFIG_TUN": "y",
    }
    assert config["kernel"]["defconfig"] == ["defconfig"]
    assert config["kernel"]["device_tree"] == {
        "directory": "amlogic",
        "name": "meson-sm1-khadas-vim3l",
    }
