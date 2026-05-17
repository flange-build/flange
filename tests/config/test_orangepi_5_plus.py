"""OrangePi 5 Plus 板级配置三层合并验证。

覆盖 rockchip-orangepi-5-plus spec 中的 board 字段、SoC 层不被覆盖、
RTL8852BE OOT 链路、无板级 dtso/board_overlays、lunch target 自动生成
五项 requirement。WiFi/BT OOT 链路与 radxa-rock5b 逐字段等价（按值比较）。
"""

from __future__ import annotations

import pytest

from builder.config.query import get_valid_targets
from builder.config.registry import discover_boards, get_board_config


@pytest.fixture(scope="module")
def boards():
    return discover_boards()


class TestOrangePi5PlusBoardDiscovery:
    """OrangePi 5 Plus 板被自动发现且字段最小完整。"""

    def test_discovered(self, boards):
        assert "orangepi-5-plus" in boards

    def test_board_identity_fields(self, boards):
        cfg = boards["orangepi-5-plus"]
        assert cfg["board"] == "orangepi-5-plus"
        assert cfg["soc"] == "rk3588"
        assert cfg["platform"] == "rockchip"
        assert cfg["kernel"]["dts"] == "rk3588-orangepi-5-plus"


class TestOrangePi5PlusMergedConfig:
    """三层合并（platform → SoC → board）后字段完整且取值正确。"""

    @pytest.fixture()
    def merged(self, boards):
        return get_board_config("orangepi-5-plus", boards=boards)

    def test_platform_layer_fields(self, merged):
        """合并后保留 platform 层字段。"""
        assert merged["vendor"] == "rockchip"
        assert merged["flash_tool"] == "upgrade_tool"
        assert merged["arch"] == "aarch64"

    def test_soc_layer_bootloader_not_overridden(self, merged):
        """SoC 层 bootloader 字段不被 board 覆盖。"""
        assert merged["bootloader"]["repo"] == "https://github.com/radxa/u-boot"
        assert merged["bootloader"]["branch"] == "next-dev-v2026.01"
        assert merged["bootloader"]["defconfig"] == "rk3588_defconfig"

    def test_soc_layer_rkbin_not_overridden(self, merged):
        """SoC 层 rkbin.mkimage_chip / ini_prefix 不被 board 覆盖。"""
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
        ]

    def test_board_layer_fields(self, merged):
        """合并后保留 board 层字段（board 名 / DTS）。"""
        assert merged["board"] == "orangepi-5-plus"
        assert merged["kernel"]["dts"] == "rk3588-orangepi-5-plus"

    def test_kernel_args_uart2_inherited(self, merged):
        """串口 console 沿用 SoC 层 UART2 1500000。"""
        assert "ttyS2,1500000" in merged["boot"]["kernel_args"]

    def test_partitions_5_entries_inherited(self, merged):
        """分区布局沿用 SoC 层 5 分区。"""
        names = [e["name"] for e in merged["partitions"]["entries"]]
        assert names == ["idbloader", "uboot", "boot", "recovery", "rootfs"]

    def test_extra_firmware_mali_csf_inherited(self, merged):
        """与 ROCK 5B 同源继承 SoC 层 mali-csf firmware 声明（panthor 驱动用）。"""
        extra = merged.get("rootfs", {}).get("extra_firmware", [])
        names = [e.get("name") for e in extra]
        assert "mali-csf" in names, (
            f"OrangePi 5 Plus merged config 应包含 mali-csf extra_firmware；实际: {names}")


class TestOrangePi5PlusRTL8852BEOOTChain:
    """RTL8852BE OOT 链路三块字段与 radxa-rock5b 等价（按值比较）。"""

    @pytest.fixture()
    def merged(self, boards):
        return get_board_config("orangepi-5-plus", boards=boards)

    @pytest.fixture()
    def rock5b(self, boards):
        return get_board_config("radxa-rock5b", boards=boards)

    def test_oot_sources_rkwifibt(self, merged):
        rkwifibt = merged["kernel"]["oot_sources"]["rkwifibt"]
        assert rkwifibt["repo"] == "https://github.com/radxa/rkwifibt.git"
        assert rkwifibt["branch"] == "develop"

    def test_oot_sources_equivalent_to_rock5b(self, merged, rock5b):
        assert merged["kernel"]["oot_sources"] == rock5b["kernel"]["oot_sources"]

    def test_oot_modules_has_rtl8852be(self, merged):
        # SoC 层无 oot_modules 基础列表，board 层 `+oot_modules` 保留 `+` 前缀。
        oot = merged["kernel"].get("oot_modules") or merged["kernel"].get("+oot_modules", [])
        labels = [m.get("label") for m in oot]
        assert any("rtl8852be" in (lbl or "") for lbl in labels), (
            f"oot_modules 应含 rtl8852be 条目；实际 labels: {labels}")

    def test_oot_modules_equivalent_to_rock5b(self, merged, rock5b):
        merged_oot = merged["kernel"].get("oot_modules") or merged["kernel"].get("+oot_modules", [])
        rock5b_oot = rock5b["kernel"].get("oot_modules") or rock5b["kernel"].get("+oot_modules", [])
        assert merged_oot == rock5b_oot

    def test_extra_firmware_has_rkwifibt(self, merged):
        extra = merged["rootfs"]["extra_firmware"]
        names = [e.get("name") for e in extra]
        assert "rkwifibt-rtl8852be" in names

    def test_extra_firmware_rkwifibt_entry_equivalent_to_rock5b(self, merged, rock5b):
        merged_rkwifibt = [e for e in merged["rootfs"]["extra_firmware"]
                           if e.get("name") == "rkwifibt-rtl8852be"]
        rock5b_rkwifibt = [e for e in rock5b["rootfs"]["extra_firmware"]
                           if e.get("name") == "rkwifibt-rtl8852be"]
        assert merged_rkwifibt == rock5b_rkwifibt


class TestOrangePi5PlusNoBoardOverlays:
    """OrangePi 5 Plus 不携带板级 dtso 与 boot.board_overlays。"""

    @pytest.fixture()
    def merged(self, boards):
        return get_board_config("orangepi-5-plus", boards=boards)

    def test_no_board_overlays(self, merged):
        """boot.board_overlays 不存在或为空列表。"""
        board_overlays = merged.get("boot", {}).get("board_overlays", [])
        assert board_overlays == [], (
            f"orangepi-5-plus 不应携带 board_overlays；实际: {board_overlays}")

    def test_no_dtso_directory(self):
        """组件目录下不存在 dtso/ 子目录与任何 .dtso 文件。"""
        from pathlib import Path
        board_dir = Path(__file__).resolve().parents[2] / "components/board/orangepi-5-plus"
        assert not (board_dir / "dtso").exists(), "components/board/orangepi-5-plus/dtso/ 不应存在"
        assert list(board_dir.rglob("*.dtso")) == [], "orangepi-5-plus 目录下不应有 .dtso 文件"


class TestOrangePi5PlusLunchTargets:
    """OrangePi 5 Plus lunch target 自动出现在可用目标列表。"""

    def test_targets_include_default_debug_and_release(self, boards):
        targets = set(get_valid_targets(boards=boards))
        assert "orangepi-5-plus-default-debug" in targets
        assert "orangepi-5-plus-default-release" in targets
