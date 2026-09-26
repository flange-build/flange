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
    kernel_config = config["kernel"]["config"]
    # 板层与 SoC 层合并的结果，binder 相关配置必须保留。
    # 不再断言精确相等：components/kernel/config.jsonnet 作为平台无关的内核
    # 基线层，会向每块板合并 USB gadget 配置，全集不再由板层与 SoC 层独占。
    for symbol in (
        "CONFIG_ANDROID_BINDERFS",
        "CONFIG_ANDROID_BINDER_IPC",
        "CONFIG_DRM_GUD",
        "CONFIG_NET",
        "CONFIG_TUN",
    ):
        assert kernel_config[symbol] == "y", symbol
    # 基线层确实参与了合并，而不是被板层/SoC 层覆盖掉。
    assert kernel_config["CONFIG_USB_CONFIGFS"] == "y"
    assert kernel_config["CONFIG_USB_ROLE_SWITCH"] == "y"
    assert config["kernel"]["defconfig"] == ["defconfig"]
    assert config["kernel"]["device_tree"] == {
        "directory": "amlogic",
        "name": "meson-sm1-khadas-vim3l",
    }


@pytest.mark.parametrize("product", ["default", "desktop"])
@pytest.mark.parametrize("variant", ["debug", "release"])
def test_rubikpi3复用qcs6490基线并声明ufs启动固件(product, variant):
    config = JsonnetConfigLoader(PROJECT_ROOT).evaluate_board(
        "thundercomm-rubikpi3", product, variant)

    validate_canonical_config(config)
    assert config["kernel"]["source"] == {"name": "linux-qcs6490"}
    assert config["kernel"]["device_tree"] == {
        "directory": "qcom",
        "name": "qcs6490-thundercomm-rubikpi3",
    }
    assert config["boot"]["kernel_args"].endswith(
        "root=PARTLABEL=rootfs rootwait pcie_pme=nomsi deferred_probe_timeout=30")
    bootloader = config["bootloader"]
    assert bootloader["ufs_rawprogram"] == [f"rawprogram{n}.xml" for n in range(1, 6)]
    assert bootloader["ufs_patch"] == [f"patch{n}.xml" for n in range(1, 6)]
    assert "ufs_provisions" not in bootloader
    assert config["partitions"]["sector_size"] == 4096
    firmware = {entry["name"]: entry for entry in config["rootfs"]["extra_firmware"]}
    assert {"rubikpi3-ap6256-wifi", "rubikpi3-ap6256-board"} <= set(firmware)
    assert {"src": "nvram.txt",
            "dest": "brcm/brcmfmac43456-sdio.thundercomm,rubikpi3.txt"} in (
        firmware["rubikpi3-ap6256-board"]["files"])
    assert "bluez" in config["rootfs"]["packages"]
    desktop = "flange-ubuntu-desktop-config" in config["rootfs"]["custom_packages"]
    assert desktop == (product == "desktop")
