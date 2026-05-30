"""Radxa Zero 板级配置三层合并验证。

覆盖 amlogic-platform spec 中 "radxa-zero 板级配置完整" 与
"radxa-zero AW-CM256SM Wi-Fi/BT 固件部署" 两条 requirement。

测试形态对齐 tests/config/test_khadas_vim3l.py：仅依赖 discover_boards /
get_board_config / get_valid_targets / resolve_config 公开 API。
"""

from __future__ import annotations

import pytest

from builder.config.query import get_valid_targets
from builder.config.registry import discover_boards, get_board_config


@pytest.fixture(scope="module")
def boards():
    return discover_boards()


class TestRadxaZeroBoardDiscovery:
    """radxa-zero 板被自动发现且字段最小完整。"""

    def test_discovered(self, boards):
        assert "radxa-zero" in boards

    def test_board_identity_fields(self, boards):
        cfg = boards["radxa-zero"]
        assert cfg["board"] == "radxa-zero"
        assert cfg["soc"] == "s905y2"
        assert cfg["platform"] == "amlogic"
        assert cfg["kernel"]["dts"] == "meson-g12a-radxa-zero"


class TestRadxaZeroMergedConfig:
    """三层合并（platform → SoC → board）后字段完整且取值正确。"""

    @pytest.fixture()
    def merged(self, boards):
        return get_board_config("radxa-zero", boards=boards)

    def test_platform_layer_fields(self, merged):
        assert merged["vendor"] == "amlogic"
        assert merged["flash_tool"] == "fastboot"
        assert merged["arch"] == "aarch64"

    def test_soc_layer_fields(self, merged):
        """合并后保留 SoC s905y2 字段（radxa-zero 不覆盖 fip_tool / dts_dir /
        kernel_args / defconfig，全部沿用 SoC 取值）。"""
        assert merged["soc"] == "s905y2"
        assert merged["repos"]["u-boot"]["branch"] == "v2024.10"
        assert merged["repos"]["linux"]["branch"] == "v6.12"
        assert (
            merged["repos"]["amlogic-boot-fip"]["repo"]
            == "https://github.com/LibreELEC/amlogic-boot-fip.git"
        )
        # bootloader：base defconfig + fastboot fragment（SoC 层 list 形态）
        assert merged["bootloader"]["defconfig"] == [
            "radxa-zero_defconfig",
            "flange_fastboot.config",
        ]
        assert merged["bootloader"]["fip_tool"] == "aml_encrypt_g12a"
        assert merged["bootloader"]["fip_family_inc"] == "g12a.inc"
        assert merged["kernel"]["defconfig"] == "defconfig"
        assert merged["kernel"]["dts_dir"] == "amlogic"

    def test_board_layer_fields(self, merged):
        assert merged["board"] == "radxa-zero"
        assert merged["kernel"]["dts"] == "meson-g12a-radxa-zero"
        assert merged["bootloader"]["fip_board_dir"] == "radxa-zero"

    def test_kernel_args_ttyaml0(self, merged):
        args = merged["boot"]["kernel_args"]
        assert "console=ttyAML0,115200n8" in args
        assert "earlycon" in args

    def test_recovery_disabled(self, merged):
        """Radxa Zero 首版不交付 recovery，board 层 enabled=False。"""
        assert merged["recovery"]["enabled"] is False

    def test_partitions_three_entries_no_recovery(self, merged):
        """board 层覆盖 SoC 分区布局：bootloader (raw 占位) + boot + rootfs；
        无 recovery（省 512MB 给 rootfs）。"""
        names = [e["name"] for e in merged["partitions"]["entries"]]
        assert names == ["bootloader", "boot", "rootfs"], (
            f"Radxa Zero 应为 bootloader + boot + rootfs；实际: {names}"
        )
        assert "recovery" not in names

    def test_bootloader_is_raw_partition(self, merged):
        """bootloader 类型必须是 raw —— image.py GPT 写入时跳过 raw 类型
        （Amlogic BootROM 走 mmc2 hw boot0 而非 user area）。"""
        entries = merged["partitions"]["entries"]
        bl = next(e for e in entries if e["name"] == "bootloader")
        assert bl["type"] == "raw"

    def test_partitions_rootfs_grows(self, merged):
        rootfs_entry = next(
            e for e in merged["partitions"]["entries"] if e["name"] == "rootfs"
        )
        assert rootfs_entry["size"] == "remaining"
        assert rootfs_entry["grow_on_first_boot"] is True

    def test_rootfs_url_ubuntu_base_24_04(self, merged):
        assert "ubuntu-base-24.04" in merged["rootfs"]["url"]
        assert "arm64" in merged["rootfs"]["url"]

    def test_rootfs_custom_packages_inherits_platform(self, merged):
        custom = merged["rootfs"]["custom_packages"]
        assert "adbd" in custom
        assert "recoveryctl" in custom
        assert "flange-rootfs-grow" in custom

    def test_rootfs_board_packages_include_bluez(self, merged):
        plus_pkgs = merged["rootfs"].get("+packages", [])
        assert "bluez" in plus_pkgs


class TestRadxaZeroFirmware:
    """AW-CM256SM (CYW43455) WiFi/BT 固件声明：覆盖
    "radxa-zero AW-CM256SM Wi-Fi/BT 固件部署" requirement 的
    "rootfs 含 AW-CM256SM 固件声明" scenario。"""

    @pytest.fixture()
    def merged(self, boards):
        return get_board_config("radxa-zero", boards=boards)

    def test_extra_firmware_single_radxa_entry(self, merged):
        extras = merged["rootfs"]["+extra_firmware"]
        names = [e["name"] for e in extras]
        assert names == ["radxa-zero-aw-cm256sm"], (
            f"Radxa Zero 应仅声明一个板级 +extra_firmware 条目；实际: {names}"
        )

    def test_extra_firmware_source_is_radxa_firmware(self, merged):
        entry = merged["rootfs"]["+extra_firmware"][0]
        assert entry["repo"] == "https://github.com/radxa-pkg/radxa-firmware.git"
        assert entry["branch"] == "main"
        assert entry["repo_subdir"] == "radxa-firmware/lib/firmware"
        assert entry["dest"] == "lib/firmware/brcm"

    def test_extra_firmware_files_wifi_nvram_clm_bt(self, merged):
        """三件套 WiFi 固件 + AW-CM256SM NVRAM + CLM + BT patchram，
        源名来自 radxa-firmware，落地名是 mainline brcmfmac/btbcm 通用名。"""
        entry = merged["rootfs"]["+extra_firmware"][0]
        files = {f["src"]: f["dest"] for f in entry["files"]}
        assert files == {
            "cypress/cyfmac43455-sdio.bin": "brcmfmac43455-sdio.bin",
            "brcm/nvram_azw256.txt": "brcmfmac43455-sdio.txt",
            "cypress/cyfmac43455-sdio.clm_blob": "brcmfmac43455-sdio.clm_blob",
            "brcm/BCM4345C0.hcd": "BCM4345C0.hcd",
        }

    def test_no_vim3l_ap6398s_firmware_leak(self, merged):
        """不得引入与 AW-CM256SM 无关的 VIM3L/AP6398S 固件文件。"""
        entry = merged["rootfs"]["+extra_firmware"][0]
        srcs = " ".join(f["src"] for f in entry["files"])
        dests = " ".join(f["dest"] for f in entry["files"])
        for token in ("4359", "ap6398s", "BCM4359"):
            assert token not in srcs
            assert token not in dests


class TestRadxaZeroNoBtattachUnit:
    """task 3.4：mainline DTS 已把 BT 声明为 uart_A serdev 子节点
    （自动绑定），不添加冗余 btattach systemd 单元。"""

    def test_no_bluetooth_service_overlay(self):
        from builder.paths import COMPONENTS_ROOT
        svc_dir = (
            COMPONENTS_ROOT / "board" / "radxa-zero"
            / "overlay" / "etc" / "systemd" / "system"
        )
        if not svc_dir.is_dir():
            return  # 无 systemd overlay 目录即满足
        units = list(svc_dir.glob("bluetooth*.service"))
        assert units == [], (
            f"Radxa Zero BT 由 DTS serdev 自动绑定，不应有 btattach 单元；"
            f"实际: {units}"
        )


class TestRadxaZeroOverlayFiles:
    """板级 overlay 文件存在且内容正确。"""

    def test_hostname_overlay_present(self):
        from builder.paths import COMPONENTS_ROOT
        path = (
            COMPONENTS_ROOT / "board" / "radxa-zero"
            / "overlay" / "etc" / "hostname"
        )
        assert path.is_file(), f"缺少 hostname overlay: {path}"
        assert path.read_text().strip() == "radxa-zero"

    def test_usbdevice_conf_present(self):
        from builder.paths import COMPONENTS_ROOT
        path = (
            COMPONENTS_ROOT / "board" / "radxa-zero"
            / "overlay" / "etc" / "usbdevice.conf"
        )
        assert path.is_file(), f"缺少 usbdevice.conf overlay: {path}"
        text = path.read_text()
        assert 'USB_PRODUCT_NAME="radxa-zero"' in text
        assert "USB_GROUP=radxa-zero" in text


class TestRadxaZeroLunchTargets:
    """radxa-zero lunch target 自动出现在可用目标列表。"""

    def test_targets_include_default_debug_and_release(self, boards):
        targets = set(get_valid_targets(boards=boards))
        assert "radxa-zero-default-debug" in targets
        assert "radxa-zero-default-release" in targets
