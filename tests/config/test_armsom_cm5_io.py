"""ArmSoM CM5 IO (RK3576) 板级配置三层合并验证。

覆盖 rockchip-armsom-cm5-io spec 中 board 配置基础字段、不覆盖 SoC GPU 路线、
lunch target 自动生成等 requirement。
"""

from __future__ import annotations

import pytest

from builder.config.query import get_valid_targets
from builder.config.registry import discover_boards, get_board_config


@pytest.fixture(scope="module")
def boards():
    return discover_boards()


class TestArmsomCM5IODiscovery:
    """armsom-cm5-io 板被自动发现且字段最小完整。"""

    def test_discovered(self, boards):
        assert "armsom-cm5-io" in boards

    def test_board_identity_fields(self, boards):
        cfg = boards["armsom-cm5-io"]
        assert cfg["board"] == "armsom-cm5-io"
        assert cfg["soc"] == "rk3576"
        assert cfg["platform"] == "rockchip"
        assert cfg["kernel"]["dts"] == "rk3576-armsom-cm5-io"


class TestArmsomCM5IOMergedConfig:
    """三层合并（platform → SoC → board）后字段完整且取值正确。"""

    @pytest.fixture()
    def merged(self, boards):
        return get_board_config("armsom-cm5-io", boards=boards)

    def test_platform_layer_fields(self, merged):
        assert merged["vendor"] == "rockchip"
        assert merged["flash_tool"] == "upgrade_tool"
        assert merged["arch"] == "aarch64"

    def test_soc_layer_fields(self, merged):
        assert merged["soc"] == "rk3576"
        assert merged["rkbin"]["mkimage_chip"] == "rk3576"
        assert merged["rkbin"]["ini_prefix"] == "RK3576"
        assert merged["rkbin"]["trust_ini_prefix"] == "RK3576"
        assert merged["bootloader"]["repo"] == "https://github.com/radxa/u-boot"
        assert merged["bootloader"]["branch"] == "next-dev-v2026.01"

    def test_board_layer_fields(self, merged):
        assert merged["board"] == "armsom-cm5-io"
        assert merged["kernel"]["dts"] == "rk3576-armsom-cm5-io"

    def test_gpu_panfrost_fragment_inherited(self, merged):
        """board 不覆盖 SoC GPU 路线，合并后仍带 panfrost fragment。"""
        assert "rk3576_panfrost.config" in merged["kernel"]["defconfig"]
        # 不串入 rk3588 的 panthor fragment
        assert "rk3588_panthor.config" not in merged["kernel"]["defconfig"]

    def test_kernel_branch_rkr5_1(self, merged):
        assert merged["kernel"]["branch"] == "linux-6.1-stan-rkr5.1"

    def test_kernel_args_uart0(self, merged):
        assert "ttyS0,1500000" in merged["boot"]["kernel_args"]

    def test_partitions_5_entries(self, merged):
        names = [e["name"] for e in merged["partitions"]["entries"]]
        assert names == ["idbloader", "uboot", "boot", "recovery", "rootfs"]

    def test_root_password_set(self, merged):
        """首版 bring-up 需 ssh 登录；ubuntu-base 默认 root 锁定，须设密码。"""
        assert merged["rootfs"]["root_password"] == "1234"

    def test_no_mali_csf_firmware(self, merged):
        """panfrost 无 CSF firmware，合并后不含 mali-csf。"""
        extra = merged.get("rootfs", {}).get("extra_firmware", [])
        names = [e.get("name") for e in extra]
        assert "mali-csf" not in names


class TestArmsomCM5IOLunchTargets:
    """armsom-cm5-io lunch target 自动出现在可用目标列表。"""

    def test_targets_include_default_debug_and_release(self, boards):
        targets = set(get_valid_targets(boards=boards))
        assert "armsom-cm5-io-default-debug" in targets
        assert "armsom-cm5-io-default-release" in targets
