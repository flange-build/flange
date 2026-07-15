"""OrangePi CM5 Tablet 板级配置三层合并验证。

覆盖 rockchip-orangepi-cm5-tablet spec 中的 board 字段、SoC 层不被覆盖、
AP6256 in-tree bcmdhd 链路（含与 cm4 +extra_firmware 等价、不引入 OOT）、
无板级 dtso/board_overlays、仅一条 bcmdhd 路径 patch、lunch target 自动
生成等 requirement。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from builder.config.query import get_valid_targets
from builder.config.registry import discover_boards, get_board_config


REPO_ROOT = Path(__file__).resolve().parents[2]
BOARD_DIR = REPO_ROOT / "components/board/orangepi-cm5-tablet"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def boards():
    return discover_boards()


class TestOrangePiCm5TabletBoardDiscovery:
    """OrangePi CM5 Tablet 板被自动发现且字段最小完整。"""

    def test_discovered(self, boards):
        assert "orangepi-cm5-tablet" in boards

    def test_board_identity_fields(self, boards):
        cfg = boards["orangepi-cm5-tablet"]
        assert cfg["board"] == "orangepi-cm5-tablet"
        assert cfg["soc"] == "rk3588s"
        assert cfg["platform"] == "rockchip"
        assert cfg["kernel"]["dts"] == "rk3588s-orangepi-cm5-tablet"


class TestOrangePiCm5TabletMergedConfig:
    """三层合并（platform → SoC → board）后字段完整且取值正确。"""

    @pytest.fixture()
    def merged(self, boards):
        return get_board_config("orangepi-cm5-tablet", boards=boards)

    def test_platform_layer_fields(self, merged):
        """合并后保留 platform 层字段。"""
        assert merged["vendor"] == "rockchip"
        assert merged["flash_tool"] == "upgrade_tool"
        assert merged["arch"] == "aarch64"

    def test_soc_layer_bootloader_not_overridden(self, merged):
        """SoC 层 bootloader 字段不被 board 覆盖。RK3588S 沿用 generic rk3588_defconfig。"""
        assert merged["bootloader"]["repo"] == "https://github.com/radxa/u-boot"
        assert merged["bootloader"]["branch"] == "next-dev-v2026.01"
        assert merged["bootloader"]["defconfig"] == "rk3588_defconfig"

    def test_soc_layer_rkbin_not_overridden(self, merged):
        """RK3588S 与 RK3588 同 die 同 BootROM，rkbin 字段沿用 rk3588。"""
        assert merged["rkbin"]["mkimage_chip"] == "rk3588"
        assert merged["rkbin"]["ini_prefix"] == "RK3588"
        assert merged["rkbin"]["trust_ini_prefix"] == "RK3588"

    def test_soc_layer_kernel_not_overridden(self, merged):
        """SoC 层 kernel.branch / defconfig list 不被 board 覆盖。"""
        assert merged["kernel"]["branch"] == "linux-6.1-stan-rkr5.1"
        assert merged["kernel"]["defconfig"] == [
            "rockchip_linux_defconfig",
            "case_insensitive_fix.config",
            "rk3588_panthor.config",
            "CONFIG_DRM_GUD=y",
        ]

    def test_board_layer_fields(self, merged):
        """合并后保留 board 层字段（board 名 / DTS）。"""
        assert merged["board"] == "orangepi-cm5-tablet"
        assert merged["kernel"]["dts"] == "rk3588s-orangepi-cm5-tablet"

    def test_kernel_args_uart2_inherited(self, merged):
        """RK3588S 调试串口沿用 SoC 层 UART2 1500000。"""
        assert "ttyS2,1500000" in merged["boot"]["kernel_args"]

    def test_partitions_5_entries_inherited(self, merged):
        """分区布局沿用 SoC 层 5 分区。"""
        names = [e["name"] for e in merged["partitions"]["entries"]]
        assert names == ["idbloader", "uboot", "boot", "recovery", "rootfs"]

    def test_extra_firmware_mali_csf_inherited(self, merged):
        """SoC 层 mali-csf firmware 声明（panthor 驱动用）被继承。"""
        extra = merged.get("rootfs", {}).get("extra_firmware", [])
        names = [e.get("name") for e in extra]
        assert "mali-csf" in names, (
            f"orangepi-cm5-tablet merged config 应包含 mali-csf extra_firmware；实际: {names}")


class TestOrangePiCm5TabletAP6256InTree:
    """AP6256 走 in-tree bcmdhd 链路：三件套固件与 cm4 等价 + 不引入 OOT 字段。"""

    @pytest.fixture()
    def merged(self, boards):
        return get_board_config("orangepi-cm5-tablet", boards=boards)

    @pytest.fixture()
    def cm4(self, boards):
        return get_board_config("orangepi-cm4", boards=boards)

    def test_extra_firmware_has_radxa_ap6256(self, merged):
        """三件套固件 entry 存在且字段值正确。"""
        extra = merged["rootfs"]["extra_firmware"]
        radxa = [e for e in extra if e.get("name") == "radxa"]
        assert len(radxa) == 1, f"应仅有一条 name=radxa entry；实际: {[e.get('name') for e in extra]}"
        e = radxa[0]
        assert e["repo"] == "https://github.com/radxa-pkg/radxa-firmware"
        assert e["branch"] == "main"
        assert e["repo_subdir"] == "radxa-firmware/lib/firmware"
        assert set(e["files"]) == {
            "brcm/fw_bcm43456c5_ag.bin",
            "brcm/nvram_ap6256.txt",
            "brcm/BCM4345C5.hcd",
        }
        assert e["dest"] == "lib/firmware"

    def test_extra_firmware_radxa_entry_equivalent_to_cm4(self, merged, cm4):
        """逐字段等价于 orangepi-cm4 同名 entry。

        cm5-tablet 在 SoC 层 (rk3588s) 已有 mali-csf entry，board 层 +extra_firmware
        被 deep_merge 合入 extra_firmware；cm4 SoC 层 (rk3566) 无 base，所以
        +extra_firmware 前缀保留。两边从两个 key 中取出 radxa entry 后逐字段比较。
        """
        def _radxa_entry(cfg):
            for key in ("extra_firmware", "+extra_firmware"):
                for e in cfg["rootfs"].get(key) or []:
                    if e.get("name") == "radxa":
                        return e
            return None
        merged_radxa = _radxa_entry(merged)
        cm4_radxa = _radxa_entry(cm4)
        assert merged_radxa is not None and cm4_radxa is not None
        assert merged_radxa == cm4_radxa

    def test_no_oot_sources(self, merged):
        """in-tree bcmdhd 路径：MUST NOT 声明 oot_sources。"""
        assert "oot_sources" not in merged["kernel"], (
            "AP6256 走 in-tree bcmdhd，不应声明 oot_sources；"
            f"实际 keys: {list(merged['kernel'].keys())}")

    def test_no_oot_modules(self, merged):
        """in-tree bcmdhd 路径：MUST NOT 声明 +oot_modules / oot_modules。"""
        assert merged["kernel"].get("oot_modules", []) == []
        assert "+oot_modules" not in merged["kernel"]


class TestOrangePiCm5TabletNoBoardOverlays:
    """orangepi-cm5-tablet 不携带板级 dtso 与 boot.board_overlays。"""

    @pytest.fixture()
    def merged(self, boards):
        return get_board_config("orangepi-cm5-tablet", boards=boards)

    def test_no_board_overlays(self, merged):
        """boot.board_overlays 不存在或为空列表。"""
        board_overlays = merged.get("boot", {}).get("board_overlays", [])
        assert board_overlays == [], (
            f"orangepi-cm5-tablet 不应携带 board_overlays；实际: {board_overlays}")

    def test_no_dtso_directory(self):
        """组件目录下不存在 dtso/ 子目录与任何 .dtso 文件。"""
        assert not (BOARD_DIR / "dtso").exists(), \
            "components/board/orangepi-cm5-tablet/dtso/ 不应存在"
        assert list(BOARD_DIR.rglob("*.dtso")) == [], \
            "orangepi-cm5-tablet 目录下不应有 .dtso 文件"


class TestOrangePiCm5TabletPatches:
    """patches/kernel/ 仅含一份 bcmdhd 路径 patch，且与 cm4 0002 等价。"""

    def test_patches_dir_contains_only_bcmdhd_patch(self):
        patches_dir = BOARD_DIR / "patches/kernel"
        assert patches_dir.is_dir(), f"{patches_dir} 应存在"
        files = sorted(p.name for p in patches_dir.iterdir() if p.is_file())
        assert files == ["0001-bcmdhd-set-fw-ampak-path-brcm.patch"], (
            f"patches/kernel/ 仅应含一份 bcmdhd patch；实际: {files}")

    def test_bcmdhd_patch_equivalent_to_cm4_0002(self):
        """与 orangepi-cm4 0002 sha256 一致（逐字节复用）。"""
        cm5 = BOARD_DIR / "patches/kernel/0001-bcmdhd-set-fw-ampak-path-brcm.patch"
        cm4 = REPO_ROOT / "components/board/orangepi-cm4/patches/kernel/0002-bcmdhd-set-fw-ampak-path-brcm.patch"
        assert _sha256(cm5) == _sha256(cm4), \
            "orangepi-cm5-tablet 的 bcmdhd patch 必须与 orangepi-cm4 0002 逐字节一致"

    def test_no_dtsi_or_npu_patch(self):
        """不携带 cm4 0001（dtsi bootargs）/ 0003（NPU disable）等价 patch。"""
        patches_dir = BOARD_DIR / "patches/kernel"
        names = [p.name for p in patches_dir.iterdir() if p.is_file()]
        for name in names:
            lname = name.lower()
            assert "bootargs" not in lname, f"不应携带 bootargs 类 patch: {name}"
            assert "dtsi" not in lname, f"不应携带 dtsi 路径类 patch: {name}"
            assert "rknpu" not in lname and "disable-npu" not in lname, \
                f"不应携带 NPU disable 类 patch: {name}"


class TestOrangePiCm5TabletOverlay:
    """overlay/etc/ 仅含 hostname；不携带 usbdevice.conf。"""

    def test_hostname_content(self):
        hostname = (BOARD_DIR / "overlay/etc/hostname").read_text()
        assert hostname.strip() == "orangepi-cm5-tablet"

    def test_no_usbdevice_conf(self):
        assert not (BOARD_DIR / "overlay/etc/usbdevice.conf").exists(), \
            "首版不携带 usbdevice.conf（与 cm4 / rock5c-lite 对齐）"


class TestOrangePiCm5TabletLunchTargets:
    """OrangePi CM5 Tablet lunch target 自动出现在可用目标列表。"""

    def test_targets_include_default_debug_and_release(self, boards):
        targets = set(get_valid_targets(boards=boards))
        assert "orangepi-cm5-tablet-default-debug" in targets
        assert "orangepi-cm5-tablet-default-release" in targets
