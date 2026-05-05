"""Radxa ROCK 5B 板级配置三层合并验证。

覆盖 rockchip-platform spec 中 "Radxa ROCK 5B 板级配置完整" requirement。
"""

from __future__ import annotations

import pytest

from builder.config.query import get_valid_targets
from builder.config.registry import discover_boards, get_board_config


@pytest.fixture(scope="module")
def boards():
    return discover_boards()


class TestROCK5BBoardDiscovery:
    """ROCK 5B 板被自动发现且字段最小完整。"""

    def test_discovered(self, boards):
        assert "radxa-rock5b" in boards

    def test_board_identity_fields(self, boards):
        cfg = boards["radxa-rock5b"]
        assert cfg["board"] == "radxa-rock5b"
        assert cfg["soc"] == "rk3588"
        assert cfg["platform"] == "rockchip"
        assert cfg["kernel"]["dts"] == "rk3588-rock-5b"


class TestROCK5BMergedConfig:
    """三层合并（platform → SoC → board）后字段完整且取值正确。"""

    @pytest.fixture()
    def merged(self, boards):
        return get_board_config("radxa-rock5b", boards=boards)

    def test_platform_layer_fields(self, merged):
        """合并后保留 platform 层字段。"""
        assert merged["vendor"] == "rockchip"
        assert merged["flash_tool"] == "upgrade_tool"
        assert merged["arch"] == "aarch64"

    def test_soc_layer_fields(self, merged):
        """合并后保留 SoC 层字段。ROCK 5B 不覆盖任何 bootloader 字段，
        全部沿用 SoC generic（避免 board-specific defconfig 绕过 extlinux）。
        """
        assert merged["soc"] == "rk3588"
        assert merged["rkbin"]["mkimage_chip"] == "rk3588"
        assert merged["rkbin"]["ini_prefix"] == "RK3588"
        assert merged["rkbin"]["trust_ini_prefix"] == "RK3588"
        assert merged["bootloader"]["repo"] == "https://github.com/radxa/u-boot"
        assert merged["bootloader"]["branch"] == "next-dev-v2024.10"
        assert merged["bootloader"]["defconfig"] == "rk3588_defconfig"

    def test_board_layer_fields(self, merged):
        """合并后保留 board 层字段（board 名 / DTS）。"""
        assert merged["board"] == "radxa-rock5b"
        assert merged["kernel"]["dts"] == "rk3588-rock-5b"

    def test_kernel_repo_branch_match_rk3566(self, merged, boards):
        """ROCK 5B 与 RK3566 板共用同一 argon BSP 分支。"""
        zero3w = get_board_config("radxa-zero3w", boards=boards)
        assert merged["kernel"]["repo"] == zero3w["kernel"]["repo"]
        assert merged["kernel"]["branch"] == zero3w["kernel"]["branch"]

    def test_kernel_args_uart2(self, merged):
        assert "ttyS2,1500000" in merged["boot"]["kernel_args"]

    def test_partitions_5_entries(self, merged):
        names = [e["name"] for e in merged["partitions"]["entries"]]
        assert names == ["idbloader", "uboot", "boot", "recovery", "rootfs"]


class TestROCK5BLunchTargets:
    """ROCK 5B lunch target 自动出现在可用目标列表。"""

    def test_targets_include_default_debug_and_release(self, boards):
        targets = set(get_valid_targets(boards=boards))
        assert "radxa-rock5b-default-debug" in targets
        assert "radxa-rock5b-default-release" in targets
