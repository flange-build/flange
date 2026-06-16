"""rk3576 SoC 配置自动发现与字段完整性 + 与 rk3588 对齐。

覆盖 rockchip-platform spec 中 "Rockchip 平台支持 RK3576 SoC 配置发现"
与 "Rockchip GPU 开源驱动 fragment 按 SoC GPU 架构选型"（SoC 层引用部分）。
"""

from __future__ import annotations

import pytest

from builder.config.registry import _discover_soc_configs, _load_soc_config
from builder.paths import PROJECT_ROOT


REQUIRED_TOP_FIELDS = (
    "platform", "soc", "arch", "vendor",
    "rkbin", "bootloader", "kernel", "boot", "partitions",
)


class TestRK3576SoCDiscovery:
    """rk3576 SoC 自动发现与字段完整性。"""

    def test_discovered_in_soc_map(self):
        configs = _discover_soc_configs(PROJECT_ROOT)
        assert "rk3576" in configs
        assert configs["rk3576"].endswith(
            "components/platform/rockchip/rk3576/config.py"
        )

    def test_load_succeeds(self):
        assert isinstance(_load_soc_config("rk3576"), dict)

    @pytest.mark.parametrize("field", REQUIRED_TOP_FIELDS)
    def test_required_top_fields(self, field):
        soc = _load_soc_config("rk3576")
        assert field in soc, f"rk3576 SoC config 缺少顶层字段 {field!r}"

    def test_identity_fields(self):
        soc = _load_soc_config("rk3576")
        assert soc["platform"] == "rockchip"
        assert soc["soc"] == "rk3576"
        assert soc["arch"] == "aarch64"
        assert soc["vendor"] == "rockchip"

    def test_rkbin_fields(self):
        soc = _load_soc_config("rk3576")
        assert soc["rkbin"]["ini_prefix"] == "RK3576"
        assert soc["rkbin"]["trust_ini_prefix"] == "RK3576"
        assert soc["rkbin"]["mkimage_chip"] == "rk3576"

    def test_kernel_args_uart0(self):
        """RK3576 调试串口在 UART0（rk3576-linux.dtsi serial-id=0），与 RK3588
        的 UART2 不同。"""
        soc = _load_soc_config("rk3576")
        assert "ttyS0,1500000" in soc["boot"]["kernel_args"]

    def test_partitions_byte_for_byte_with_rk3588(self):
        """首版沿用 RK3588 分区布局。"""
        rk3576 = _load_soc_config("rk3576")
        rk3588 = _load_soc_config("rk3588")
        assert rk3576["partitions"] == rk3588["partitions"]


class TestRK3576KernelAlignsRK3588:
    """内核源/分支/base defconfig 与 rk3588 对齐，仅 GPU fragment 换 panfrost。"""

    def test_kernel_repo_branch_match_rk3588(self):
        rk3576 = _load_soc_config("rk3576")
        rk3588 = _load_soc_config("rk3588")
        assert rk3576["kernel"]["repo"] == rk3588["kernel"]["repo"]
        assert rk3576["kernel"]["branch"] == rk3588["kernel"]["branch"]
        assert rk3576["kernel"]["branch"] == "linux-6.1-stan-rkr5.1"
        assert rk3576["kernel"]["dts_dir"] == rk3588["kernel"]["dts_dir"]

    def test_defconfig_base_aligned_gpu_fragment_panfrost(self):
        """base + case_insensitive 与 rk3588 一致；GPU fragment 换 panfrost。"""
        rk3576 = _load_soc_config("rk3576")
        assert rk3576["kernel"]["defconfig"] == [
            "rockchip_linux_defconfig",
            "case_insensitive_fix.config",
            "panfrost.config",
        ]

    def test_no_mali_csf_firmware(self):
        """panfrost 无 CSF firmware 依赖，rk3576 不带 mali-csf（区别 rk3588 panthor）。"""
        soc = _load_soc_config("rk3576")
        extra = soc.get("rootfs", {}).get("extra_firmware", [])
        names = [e.get("name") for e in extra]
        assert "mali-csf" not in names


class TestRK3576NotPollutingOthers:
    """rk3576 与 rk3588 字段相互独立，GPU fragment 不串味。"""

    def test_mkimage_chip_distinct(self):
        assert _load_soc_config("rk3576")["rkbin"]["mkimage_chip"] == "rk3576"
        assert _load_soc_config("rk3588")["rkbin"]["mkimage_chip"] == "rk3588"

    def test_gpu_fragment_distinct(self):
        rk3576 = _load_soc_config("rk3576")
        rk3588 = _load_soc_config("rk3588")
        assert "panfrost.config" in rk3576["kernel"]["defconfig"]
        assert "rk3588_panthor.config" in rk3588["kernel"]["defconfig"]
        assert "panfrost.config" not in rk3588["kernel"]["defconfig"]
        # rk3588 的 panthor 路线不受本变更影响
        assert "rk3588_panthor.config" not in rk3576["kernel"]["defconfig"]
