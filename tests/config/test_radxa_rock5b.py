"""Radxa ROCK 5B 板级配置三层合并验证。

覆盖 rockchip-platform spec 中 "Radxa ROCK 5B 板级配置完整" requirement。
"""

from __future__ import annotations

import pytest

from builder.config.query import get_valid_targets
from builder.config.registry import discover_boards, get_board_config, resolve_config


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
        assert merged["bootloader"]["branch"] == "next-dev-v2026.01"
        assert merged["bootloader"]["defconfig"] == "rk3588_defconfig"

    def test_board_layer_fields(self, merged):
        """合并后保留 board 层字段（board 名 / DTS）。"""
        assert merged["board"] == "radxa-rock5b"
        assert merged["kernel"]["dts"] == "rk3588-rock-5b"

    def test_kernel_repo_match_rk3566_branch_diverged(self, merged, boards):
        """ROCK 5B 与 RK3566 板共用同一 argon BSP 仓库，但 branch 刻意分流：
        RK3588 走 rkr5.1（修复 mali_kbase r0p0 status 5），RK3566 仍 rkr4.1。"""
        zero3w = get_board_config("radxa-zero3w", boards=boards)
        assert merged["kernel"]["repo"] == zero3w["kernel"]["repo"]
        assert merged["kernel"]["branch"] == "linux-6.1-stan-rkr5.1"
        assert merged["kernel"]["branch"] != zero3w["kernel"]["branch"]

    def test_kernel_args_uart2(self, merged):
        assert "ttyS2,1500000" in merged["boot"]["kernel_args"]

    def test_partitions_5_entries(self, merged):
        names = [e["name"] for e in merged["partitions"]["entries"]]
        assert names == ["idbloader", "uboot", "boot", "recovery", "rootfs"]

    def test_extra_firmware_mali_csf_inherited(self, merged):
        """ROCK 5B 必须继承 SoC 层的 mali-csf firmware 声明，确保 panthor
        驱动 request_firmware 能命中 /lib/firmware/arm/mali/arch10.8/。"""
        extra = merged.get("rootfs", {}).get("extra_firmware", [])
        names = [e.get("name") for e in extra]
        assert "mali-csf" in names, (
            f"ROCK 5B merged config 应包含 mali-csf extra_firmware；实际: {names}")

    def test_root_password_set(self, merged):
        """ROCK 5B 必须设 rootfs.root_password。
        ubuntu-base 默认 root 是锁定态（/etc/shadow 字段为 *），不设此字段
        rootfs build 后 root 无法登录。值与其他 rockchip 板（tspi-rk3566 /
        radxa-cubie-a7z）保持一致 1234，方便开发期切板调试。"""
        assert merged["rootfs"]["root_password"] == "1234"

    def test_mali_valhall_compat_overlay_built_but_not_default(self, merged):
        """mali-valhall-compat overlay 仍编进 boot 分区作 emergency rollback，
        但不默认应用。主线已切 mainline panthor，dts 原始 arm,mali-valhall-csf
        compatible 直接被 panthor of_match 命中，无需 overlay；overlay 留作
        万一 panthor 起不来时手动改 extlinux 切回 mali_kbase 用。"""
        compat = "rk3588-rock-5b-mali-valhall-compat.dtbo"
        assert compat in merged["boot"].get("board_overlays", [])
        assert compat not in merged["boot"].get("default_overlays", [])


class TestROCK5BLunchTargets:
    """ROCK 5B lunch target 自动出现在可用目标列表。"""

    def test_targets_include_default_debug_and_release(self, boards):
        targets = set(get_valid_targets(boards=boards))
        assert "radxa-rock5b-default-debug" in targets
        assert "radxa-rock5b-default-release" in targets

    def test_targets_include_meizu_e3_bringup(self, boards):
        """meizu-e3-bringup product 的两个 variant 目标也应出现。"""
        targets = set(get_valid_targets(boards=boards))
        assert "radxa-rock5b-meizu-e3-bringup-debug" in targets
        assert "radxa-rock5b-meizu-e3-bringup-release" in targets


class TestROCK5BMeizuE3ProductSplit:
    """魅族 E3 屏栈仅在 meizu-e3-bringup product 下生效；default 裸机不带。"""

    @pytest.fixture()
    def cfg_default(self, boards):
        return resolve_config("radxa-rock5b", "default", "debug", boards=boards)

    @pytest.fixture()
    def cfg_bringup(self, boards):
        return resolve_config(
            "radxa-rock5b", "meizu-e3-bringup", "debug", boards=boards)

    def test_panel_overlay_bringup_only(self, cfg_default, cfg_bringup):
        """panel dtbo 经 packages 机制注入 package_overlays 并声明为默认应用，
        仅 meizu-e3-bringup product 启用包时出现；default 裸机不带。"""
        panel = "rk3588-rock-5b-meizu-e3-panel.dtbo"
        assert panel not in cfg_default["boot"].get("package_overlays", [])
        assert panel not in cfg_default["boot"].get("default_overlays", [])
        assert panel in cfg_bringup["boot"]["package_overlays"]
        assert panel in cfg_bringup["boot"]["default_overlays"]

    def test_panel_oot_drivers_bringup_only(self, cfg_default, cfg_bringup):
        """sec_ts 触摸 + sgm37604a 背光两个 OOT 驱动仅 bringup 编译；default
        不挂屏不带（避免裸机镜像里编入 dead modules）。"""
        def labels(cfg):
            return [m.get("label", "") for m in cfg["kernel"].get("oot_modules", [])]
        default_labels = " ".join(labels(cfg_default))
        bringup_labels = " ".join(labels(cfg_bringup))
        assert "meizu-e3-panel/sec_ts" not in default_labels
        assert "meizu-e3-panel/sgm37604a" not in default_labels
        assert "meizu-e3-panel/sec_ts" in bringup_labels
        assert "meizu-e3-panel/sgm37604a" in bringup_labels

    def test_rtl8852be_shared_by_both_products(self, cfg_default, cfg_bringup):
        """板载 RTL8852BE WiFi/BT 是裸机基础能力，两个 product 都带（OOT 模块 +
        BT 固件均与屏无关）。"""
        for cfg in (cfg_default, cfg_bringup):
            labels = " ".join(m.get("label", "") for m in cfg["kernel"]["oot_modules"])
            assert "rtl8852be" in labels
            fw_names = [e["name"] for e in cfg["rootfs"].get("extra_firmware", [])]
            assert "rkwifibt-rtl8852be" in fw_names
