"""QCS6490 Jsonnet 代表路径的 canonical 语义测试。"""

import pytest

from builder.config.jsonnet import JsonnetConfigLoader
from builder.config.query import get_valid_targets, parse_target
from builder.config.registry import discover_boards
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
    # 内核构建的 KVM 组合 DTB：UEFI Hypervisor Override=Auto 时据 /chosen/radxa,enable-kvm 进 EL2。
    assert config["kernel"]["device_tree"]["name"] == (
        "qcs6490-radxa-dragon-q6a-kvm")
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


def _mainline_kernel_patch_names():
    names = set()
    for layer in ("platform/qualcommqcs6490", "board/thundercomm-rubikpi3"):
        patch_dir = PROJECT_ROOT / "components" / layer / "patches/kernel"
        names |= {patch.name for patch in patch_dir.glob("*.patch")}
    return names


@pytest.mark.parametrize("product", ["default", "desktop"])
@pytest.mark.parametrize("variant", ["debug", "release"])
def test_rubikpi3使用厂商内核并声明ufs启动固件(product, variant):
    config = JsonnetConfigLoader(PROJECT_ROOT).evaluate_board(
        "thundercomm-rubikpi3", product, variant)

    validate_canonical_config(config)
    kernel = config["kernel"]
    assert kernel["source"] == {"name": "rubikpi-linux"}
    assert config["sources"]["rubikpi-linux"]["url"] == (
        "https://github.com/rubikpi-ai/linux.git")
    assert config["sources"]["rubikpi-linux"]["commit"] == (
        "a579877ac6b4afc6df09d8e53564dfb08d9d693f")
    assert kernel["defconfig"] == [
        "qcom_defconfig", "qcom_addons.config", "rubikpi3.config"]
    # 平台层与板级补丁全部针对 mainline radxa/kernel，厂商树上必须全部排除。
    assert set(kernel["exclude_patches"]) == _mainline_kernel_patch_names()
    assert kernel["device_tree"] == {
        "directory": "qcom",
        "name": "qcs6490-thundercomm-rubikpi3",
        "build_overlays": ["rubikpi3-video.dtbo"],
    }
    assert config["boot"]["overlays"]["board"] == ["rubikpi3-video.dtbo"]
    assert config["boot"]["overlays"]["enabled"] == []
    assert kernel["oot_sources"] == {
        "video-driver": {"source": {"name": "qcom-video-driver"}}}
    assert kernel["oot_modules"][0]["ko_pattern"] == ["{video_driver_src}/iris_vpu.ko"]
    assert config["boot"]["kernel_args"].endswith(
        "root=PARTLABEL=rootfs rootwait pcie_pme=nomsi deferred_probe_timeout=30")
    bootloader = config["bootloader"]
    assert bootloader["ufs_rawprogram"] == [f"rawprogram{n}.xml" for n in range(1, 6)]
    assert bootloader["ufs_patch"] == [f"patch{n}.xml" for n in range(1, 6)]
    assert "ufs_provisions" not in bootloader
    # 统一 EL1：保持固件包默认（Gunyah）xbl_config。
    assert "ufs_file_overrides" not in bootloader
    assert config["partitions"]["sector_size"] == 4096
    firmware = {entry["name"]: entry for entry in config["rootfs"]["extra_firmware"]}
    # 厂商 config 用 bcmdhd：固件布局与 rubikpi3-firmware 的 Makefile install 一致。
    assert firmware["rubikpi3-ap6256"]["source"] == {
        "name": "rubikpi3-firmware", "subpath": "lib/firmware"}
    assert firmware["rubikpi3-ap6256"]["files"] == [
        "fw_bcm43456c5_ag.bin", "nvram.txt", "config.txt", "brcm/BCM4345C5.hcd"]
    assert "radxa-firmware" not in config["sources"]
    assert "bluez" in config["rootfs"]["packages"]
    desktop = "flange-ubuntu-desktop-config" in config["rootfs"]["custom_packages"]
    assert desktop == (product == "desktop")


@pytest.mark.parametrize("variant", ["debug", "release"])
def test_rubikpi3_mainline_product以el2运行soc层内核(variant):
    config = JsonnetConfigLoader(PROJECT_ROOT).evaluate_board(
        "thundercomm-rubikpi3", "mainline", variant)

    validate_canonical_config(config)
    kernel = config["kernel"]
    # 与 Q6A 相同的 SoC 层 mainline 内核，平台层与板级补丁全部应用。
    assert kernel["source"] == {"name": "linux-qcs6490"}
    assert kernel["defconfig"] == [
        "defconfig", "qcom_module.config", "radxa.config", "radxa_custom.config"]
    assert "exclude_patches" not in kernel
    assert "oot_modules" not in kernel
    assert len(_mainline_kernel_patch_names()) == 10
    assert kernel["device_tree"] == {
        "directory": "qcom",
        "name": "qcs6490-thundercomm-rubikpi3",
        "build_overlays": ["rubikpi3-el2.dtbo"],
    }
    assert config["boot"]["overlays"]["board"] == ["rubikpi3-el2.dtbo"]
    assert config["bootloader"]["ufs_file_overrides"] == {
        "xbl_config.elf": "xbl_config_kvm.elf"}
    assert set(config["sources"]).isdisjoint({"rubikpi-linux", "qcom-video-driver"})
    firmware = {entry["name"]: entry for entry in config["rootfs"]["extra_firmware"]}
    assert "rubikpi3-ap6256" not in firmware
    assert firmware["rubikpi3-ap6256-wifi"]["source"]["name"] == "radxa-firmware"
    assert firmware["rubikpi3-ap6256-wifi"]["files"] == [
        "brcm/brcmfmac43456-sdio.bin", "brcm/brcmfmac43456-sdio.clm_blob"]
    assert firmware["rubikpi3-ap6256-board"]["files"][0] == {
        "src": "nvram.txt", "dest": "brcm/brcmfmac43456-sdio.thundercomm,rubikpi3.txt"}
    assert "bluez" in config["rootfs"]["packages"]
    assert "flange-ubuntu-desktop-config" not in config["rootfs"]["custom_packages"]


def test_rubikpi3不再提供el1_product():
    boards = discover_boards()
    targets = [t for t in get_valid_targets(boards) if t.startswith("thundercomm-rubikpi3-")]
    assert sorted(targets) == [
        f"thundercomm-rubikpi3-{product}-{variant}"
        for product in ("default", "desktop", "mainline") for variant in ("debug", "release")]
    with pytest.raises(Exception, match="thundercomm-rubikpi3-el1-release"):
        parse_target("thundercomm-rubikpi3-el1-release", boards)
