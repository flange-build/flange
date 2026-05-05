"""rk3588 / rk3588s SoC 配置自动发现与字段完整性。

覆盖 rockchip-platform spec 中以下 requirements：
- Rockchip 平台支持 RK3588 SoC 配置发现
- Rockchip 平台支持 RK3588S SoC 配置发现
"""

from __future__ import annotations

import pytest

from builder.config.registry import _discover_soc_configs, _load_soc_config
from builder.paths import PROJECT_ROOT


REQUIRED_TOP_FIELDS = (
    "platform", "soc", "arch", "vendor",
    "rkbin", "bootloader", "kernel", "boot", "partitions",
)


class TestRK3588SoCDiscovery:
    """rk3588 SoC 自动发现与字段完整性。"""

    def test_discovered_in_soc_map(self):
        configs = _discover_soc_configs(PROJECT_ROOT)
        assert "rk3588" in configs
        assert configs["rk3588"].endswith(
            "components/platform/rockchip/rk3588/config.py"
        )

    def test_load_succeeds(self):
        soc = _load_soc_config("rk3588")
        assert isinstance(soc, dict)

    @pytest.mark.parametrize("field", REQUIRED_TOP_FIELDS)
    def test_required_top_fields(self, field):
        soc = _load_soc_config("rk3588")
        assert field in soc, f"rk3588 SoC config 缺少顶层字段 {field!r}"

    def test_identity_fields(self):
        soc = _load_soc_config("rk3588")
        assert soc["platform"] == "rockchip"
        assert soc["soc"] == "rk3588"
        assert soc["arch"] == "aarch64"
        assert soc["vendor"] == "rockchip"

    def test_rkbin_fields(self):
        soc = _load_soc_config("rk3588")
        assert soc["rkbin"]["ini_prefix"] == "RK3588"
        assert soc["rkbin"]["trust_ini_prefix"] == "RK3588"
        assert soc["rkbin"]["mkimage_chip"] == "rk3588"

    def test_bootloader_fields(self):
        soc = _load_soc_config("rk3588")
        assert soc["bootloader"]["repo"] == "https://github.com/radxa/u-boot"
        # next-dev-v2024.10：含完整 RK3588 板级 defconfig 与 python2 shebang
        # （配套 platform 层 decode_bl31 patch）。详见 rk3588/config.py 注释。
        assert soc["bootloader"]["branch"] == "next-dev-v2024.10"
        assert soc["bootloader"]["defconfig"] == "rk3588_defconfig"

    def test_kernel_fields_match_rk3566(self):
        """RK3588 与 RK3566 沿用同一 argon BSP 分支与 defconfig。"""
        rk3588 = _load_soc_config("rk3588")
        rk3566 = _load_soc_config("rk3566")
        assert rk3588["kernel"]["repo"] == rk3566["kernel"]["repo"]
        assert rk3588["kernel"]["branch"] == rk3566["kernel"]["branch"]
        assert rk3588["kernel"]["defconfig"] == rk3566["kernel"]["defconfig"]
        assert rk3588["kernel"]["dts_dir"] == rk3566["kernel"]["dts_dir"]

    def test_kernel_args_uart2(self):
        soc = _load_soc_config("rk3588")
        assert "ttyS2,1500000" in soc["boot"]["kernel_args"]

    def test_partitions_layout(self):
        """首版沿用 RK3566 5 分区布局。"""
        soc = _load_soc_config("rk3588")
        names = [e["name"] for e in soc["partitions"]["entries"]]
        assert names == ["idbloader", "uboot", "boot", "recovery", "rootfs"]

    def test_partitions_byte_for_byte_with_rk3566(self):
        rk3588 = _load_soc_config("rk3588")
        rk3566 = _load_soc_config("rk3566")
        assert rk3588["partitions"] == rk3566["partitions"]


class TestRK3588sSoCDiscovery:
    """rk3588s SoC 自动发现与字段完整性（通路占位）。"""

    def test_discovered_in_soc_map(self):
        configs = _discover_soc_configs(PROJECT_ROOT)
        assert "rk3588s" in configs

    def test_load_succeeds_without_board(self):
        """SoC 自动发现不依赖 board 存在 — rk3588s 暂无板，仍 MUST 可加载。"""
        soc = _load_soc_config("rk3588s")
        assert soc["soc"] == "rk3588s"
        assert soc["platform"] == "rockchip"

    @pytest.mark.parametrize("field", REQUIRED_TOP_FIELDS)
    def test_required_top_fields(self, field):
        soc = _load_soc_config("rk3588s")
        assert field in soc, f"rk3588s SoC config 缺少顶层字段 {field!r}"

    def test_rkbin_shares_with_rk3588(self):
        """RK3588 与 RK3588S 同 die 同 BootROM，rkbin 字段全部相同。"""
        rk3588 = _load_soc_config("rk3588")
        rk3588s = _load_soc_config("rk3588s")
        assert rk3588s["rkbin"] == rk3588["rkbin"]

    def test_mkimage_chip_is_rk3588(self):
        soc = _load_soc_config("rk3588s")
        assert soc["rkbin"]["mkimage_chip"] == "rk3588"


class TestRK3588NotPollutingRK3566:
    """rk3588 与 rk3566 字段相互独立，不串味。"""

    def test_mkimage_chip_distinct(self):
        rk3566 = _load_soc_config("rk3566")
        rk3588 = _load_soc_config("rk3588")
        assert rk3566["rkbin"]["mkimage_chip"] == "rk3568"
        assert rk3588["rkbin"]["mkimage_chip"] == "rk3588"

    def test_defconfig_distinct(self):
        rk3566 = _load_soc_config("rk3566")
        rk3588 = _load_soc_config("rk3588")
        assert rk3566["bootloader"]["defconfig"] == "rk3568_defconfig"
        assert rk3588["bootloader"]["defconfig"] == "rk3588_defconfig"
