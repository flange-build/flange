"""ATK-RK3506B 的 GPT/SPI NAND/UBI 与 AMP 板级配置测试。"""

from __future__ import annotations

import copy
import re
from pathlib import Path

import pytest

from builder.config.query import get_valid_targets
from builder.config.registry import discover_boards, resolve_config
from builder.config.validate import ConfigError, validate_config
from builder.flash import FlashConfig, FlashConfigGenerator, generate_parameter_txt
from builder.partition.rockchip import (
    parse_parameter_text,
    validate_parameter_capacity,
)
from builder.partition.size import parse_size, resolve_image_size


@pytest.fixture(scope="module")
def boards():
    return discover_boards()


@pytest.fixture(params=["debug", "release"])
def config(boards, request):
    return resolve_config(
        "atk-rk3506b", "default", request.param, boards=boards)


def test_board_is_discovered_with_debug_and_release_targets(boards):
    assert "atk-rk3506b" in boards
    targets = set(get_valid_targets(boards=boards))
    assert "atk-rk3506b-default-debug" in targets
    assert "atk-rk3506b-default-release" in targets


def test_merged_config_uses_requested_kernel_dts_and_arm32(config):
    assert config["board"] == "atk-rk3506b"
    assert config["soc"] == "rk3506b"
    assert config["platform"] == "rockchip"
    assert config["arch"] == "armhf"
    assert config["kernel"]["repo"] == (
        "ssh://git@gitlab-r.eric3u.xyz:20022/argon/kernel.git"
    )
    assert config["kernel"]["branch"] == "linux-6.1-stan-rkr5.1"
    assert config["kernel"]["dts"] == (
        "rk3506b-alientek-mipi720x1280-nand-ubi-ubifs-amp-linux"
    )
    assert config["kernel"]["arch"] == "arm"
    assert config["kernel"]["cross_compile"] == (
        "/opt/arm-linux-gcc10/bin/arm-none-linux-gnueabihf-"
    )
    assert config["kernel"]["image"] == "zImage"
    assert config["kernel"]["defconfig"][:4] == [
        "rk3506_defconfig",
        "rk3506-display.config",
        "rockchip_amp.config",
        "case_insensitive_fix.config",
    ]
    assert "CONFIG_MTD_SPI_NAND=y" in config["kernel"]["defconfig"]
    assert "CONFIG_RPMSG_CHAR=y" in config["kernel"]["defconfig"]
    assert config["bootloader"]["cross_compile"] == (
        "/opt/arm-linux-gcc10/bin/arm-none-linux-gnueabihf-"
    )
    assert config["bootloader"]["defconfig"] == [
        "alientek_rk3506_defconfig",
        "rk-amp.config",
    ]
    assert config["bootloader"]["idbloader_selfbuilt_spl"] is True
    fit_pack = config["bootloader"]["fit_pack"]
    assert fit_pack["external_data_offset"] == "0x1200"
    assert fit_pack["slot_size_kb"] == 2048
    assert fit_pack["copies"] == 2


def test_hardware_and_minimal_rtt_amp_contract(config):
    assert config["memory"]["size"] == "512M"
    assert config["storage"]["type"] == "spinand"
    assert config["storage"]["size"] == "512M"
    assert not config.get("flash_storage")
    assert config["recovery"]["enabled"] is False
    assert config["amp"]["enabled"] is True
    assert config["amp"]["mode"] == "rt-thread"
    assert config["amp"]["app"] == "rk3506_amp_uart4_rtt_demo"
    assert config["rootfs"]["image_format"] == "ubi"
    assert config["rootfs"]["custom_packages"] == ["adbd"]


def test_rtl8733bu_uses_fixed_usb_oot_drivers(config):
    """RTL8733BUUA 的 WiFi/BT 均使用固定版本的 USB OOT driver。"""
    fragments = config["kernel"]["defconfig"]
    assert "rk3506-wifibt.config" in fragments
    for expected in (
        "# CONFIG_BCMDHD is not set",
        "# CONFIG_AP6XXX is not set",
        "# CONFIG_WL_ROCKCHIP is not set",
        "# CONFIG_RFKILL_RK is not set",
        "# CONFIG_BT_HCIUART is not set",
        "# CONFIG_BT_HCIBTUSB is not set",
    ):
        assert expected in fragments

    sources = config["kernel"]["oot_sources"]
    assert sources["rtl8733bu_wifi"]["repo"] == (
        "https://github.com/wirenboard/rtl8733bu.git"
    )
    assert sources["rtl8733bu_wifi"]["commit"] == (
        "2d9048be60759206b8db5e2370420333ef0b8478"
    )
    assert sources["rtl8733bu_bt"]["repo"] == (
        "https://gitee.com/fengyuzhong/rtl8733bu-bt.git"
    )
    assert sources["rtl8733bu_bt"]["commit"] == (
        "dc7b30b4b9d2c5437a80bfaff6c8a77c97642778"
    )

    modules = {
        module["label"]: module
        for module in config["kernel"]["oot_modules"]
    }
    wifi = modules["RTL8733BU USB WiFi"]
    assert wifi["dir"] == "{rtl8733bu_wifi_src}"
    assert wifi["ko_pattern"] == [
        "{rtl8733bu_wifi_src}/8733bu.ko",
    ]
    assert wifi["pre_build"][0] == (
        "git -C {rtl8733bu_wifi_src} checkout -- ."
    )
    assert wifi["pre_build"][1].endswith(
        "rtl8733bu/0001-disable-removed-regulatory-flag.patch"
    )
    assert "CONFIG_RTW_DEBUG=n" in wifi["make_args"]
    assert "CONFIG_PROC_DEBUG=n" in wifi["make_args"]
    assert (
        "USER_EXTRA_CFLAGS=-Wno-unused-function "
        "-Wno-discarded-qualifiers"
    ) in wifi["make_args"]
    assert "KSRC={kernel_src}" in wifi["make_args"]

    bluetooth = modules["RTL8733BU USB Bluetooth"]
    assert bluetooth["dir"] == (
        "{rtl8733bu_bt_src}/usb/bluetooth_usb_driver"
    )
    assert bluetooth["ko_pattern"] == [
        (
            "{rtl8733bu_bt_src}/usb/bluetooth_usb_driver/"
            "rtk_btusb.ko"
        ),
    ]


def test_rtl8733bu_rootfs_is_minimal_and_reproducible(config):
    """只追加 BlueZ 与同源的 RTL8733BU Bluetooth firmware。"""
    packages = config["rootfs"]["packages"]
    assert "bluez" in packages
    assert "network-manager" in packages
    assert "wpasupplicant" in packages
    assert "linux-firmware" not in packages

    entries = [
        entry for entry in config["rootfs"]["extra_firmware"]
        if entry.get("name") == "rtl8733bu-bluetooth"
    ]
    assert len(entries) == 1
    firmware = entries[0]
    assert firmware == {
        "name": "rtl8733bu-bluetooth",
        "source": "oot:rtl8733bu_bt",
        "repo_subdir": "rtkbt-firmware/lib/firmware",
        "files": [
            "rtl8733bu_fw",
            "rtl8733bu_config",
        ],
        "dest": "lib/firmware",
    }


def test_rtl8733bu_does_not_add_wifi_bluetooth_dts_patch():
    """USB composite device 不应通过 DTS patch 伪造 SDIO/UART 路由。"""
    patch_dir = Path("components/board/atk-rk3506b/patches/kernel")
    patches = sorted(patch_dir.glob("*.patch"))
    assert patches
    assert "0002-enable-ap6256-wifi-bluetooth.patch" not in {
        patch.name for patch in patches
    }

    patch_text = "\n".join(
        patch.read_text(encoding="utf-8") for patch in patches
    ).lower()
    for forbidden in (
        "ap6256",
        "rtl8733bu",
        "sdio_pwrseq",
        "wireless-wlan",
        "&uart5",
        "bcm4345c5",
    ):
        assert forbidden not in patch_text


def test_rtl8733bu_has_only_minimal_oot_compatibility_patch():
    """OOT patch 只禁用当前 Linux 6.1 已移除的 regulatory flag。"""
    patch_dir = Path("components/board/atk-rk3506b/patches/rtl8733bu")
    patches = sorted(patch_dir.glob("*.patch"))
    assert [patch.name for patch in patches] == [
        "0001-disable-removed-regulatory-flag.patch",
    ]

    patch_text = patches[0].read_text(encoding="utf-8")
    assert patch_text.count("REGULATORY_IGNORE_STALE_KICKOFF") == 3
    assert "sdio" not in patch_text.lower()
    assert "uart" not in patch_text.lower()
    assert "dts" not in patch_text.lower()


def test_usb_gadget_modules_follow_atk_sdk_load_order():
    """USB gadget 模块顺序应与 ATK Linux 6.1 SDK 保持一致。"""
    modules_file = Path(
        "components/board/atk-rk3506b/overlay/etc/modules-load.d/"
        "flange-usbgadget.conf"
    )
    modules = [
        line.strip()
        for line in modules_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert modules == ["phy-rockchip-inno-usb2", "usb_f_fs", "dwc2"]


def test_gpt_layout_matches_rk3566_order_and_512_mib_boundary(config):
    partitions = config["partitions"]
    assert partitions["format"] == "gpt"
    assert partitions["sector_size"] == 512
    entries = partitions["entries"]
    assert [entry["name"] for entry in entries] == [
        "idbloader", "uboot", "boot", "recovery", "amp", "rootfs"
    ]
    assert entries.index(next(e for e in entries if e["name"] == "amp")) < (
        entries.index(next(e for e in entries if e["name"] == "rootfs"))
    )

    resolved_end = max(
        int(entry["offset"], 0) + resolve_image_size(entry).sectors
        for entry in entries
    )
    capacity = parse_size(config["storage"]["size"]).sectors
    assert resolved_end + 2048 == capacity


def test_generated_parameter_is_gpt_and_rootfs_is_mtd5(config):
    text = generate_parameter_txt(
        config["partitions"]["entries"], machine="RK3506")
    assert "TYPE: GPT" in text
    entries = parse_parameter_text(text)
    assert entries[4].name == "amp"
    assert entries[5].name == "rootfs"
    validate_parameter_capacity(
        entries, parse_size(config["storage"]["size"]).bytes)


def test_ubi_geometry_is_derived_from_414_mib_partition(config):
    ubi = config["rootfs"]["ubi"]
    assert config["rootfs"]["image_format"] == "ubi"
    assert ubi["min_io_size"] == 2048
    assert ubi["peb_size"] == 131072
    assert ubi["subpage_size"] == 2048
    assert ubi["vid_hdr_offset"] == 2048
    assert ubi["leb_size"] == 126976
    assert ubi["max_leb_count"] == 4096
    assert ubi["space_fixup"] is True
    assert ubi["mtd_index"] == 5
    assert ubi["reserved_pebs"] == 82

    partition_pebs = 414 * 1024 * 1024 // ubi["peb_size"]
    volume_lebs = partition_pebs - 80 - 1 - 1 - 2
    assert ubi["volume_size"] == f"{volume_lebs * ubi['leb_size']}B"
    validate_config(config)


def test_gpt_tail_overflow_is_rejected(config):
    oversized = copy.deepcopy(config)
    rootfs = next(
        entry for entry in oversized["partitions"]["entries"]
        if entry["name"] == "rootfs")
    rootfs["size"] = "415M"

    with pytest.raises(ConfigError, match="GPT 分区末端"):
        validate_config(oversized)


def test_flash_config_generates_parameter_from_gpt_entries(config, tmp_path):
    output = FlashConfigGenerator().generate(config, tmp_path)
    flash = FlashConfig.from_json(output)

    assert flash.partition_format == "gpt"
    assert flash.storage_type == "spinand"
    assert flash.storage == ""
    assert flash.parameter == "parameter.txt"
    assert flash.soc == "rk3506b"
    assert len(flash.parameter_sha256) == 64
    assert flash.identity.chip_patterns
    assert flash.identity.storage_patterns
    rci_output = "Chip Info: 46 30 35 33 AD 8 B1 80\n\nF053\n"
    assert any(
        re.search(pattern, rci_output, re.I)
        for pattern in flash.identity.chip_patterns
    )
    storage_output = "Flash ID:53 4E 41 4E 44\n\nSNAND\n"
    assert any(
        re.search(pattern, storage_output, re.I)
        for pattern in flash.identity.storage_patterns
    )
    assert flash.rootfs_mtd_index == 5
    assert (tmp_path / "parameter.txt").is_file()
    by_name = {part.name: part for part in flash.partitions}
    assert "idbloader" not in by_name
    assert by_name["amp"].image == "amp/amp.img"
    assert by_name["rootfs"].image == "rootfs/rootfs.ubi"
    assert by_name["rootfs"].type == "ubi"
    assert "recovery" not in by_name


def test_committed_atk_configuration_has_no_developer_absolute_path():
    root = Path(__file__).resolve().parents[2]
    paths = [
        root / "components/board/atk-rk3506b/config.py",
        root / "components/platform/rockchip/rk3506b/config.py",
        root / "docs/boards/atk-rk3506b.md",
    ]
    paths.extend((
        root / "openspec/changes/add-rk3506b-atk-rk3506b"
    ).rglob("*.md"))
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "/Users/" not in text
        assert "kernel-rockchip" not in text
