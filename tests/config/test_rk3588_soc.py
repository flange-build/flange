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
        # next-dev-v2026.01：含完整 RK3588 板级 defconfig 与 python3 shebang
        # decode_bl31.py（platform 层 decode_bl31 patch 已删除）。详见
        # rk3566/config.py 关于整平台切到 v2026.01 的原因记录。
        assert soc["bootloader"]["branch"] == "next-dev-v2026.01"
        assert soc["bootloader"]["defconfig"] == "rk3588_defconfig"

    def test_kernel_branch_rkr5_1(self):
        """RK3566/3568/3588 统一走 rkr5.1（不带 -buildroot 后缀），共用同一
        argon BSP 仓库；GPU 驱动按 SoC 用 defconfig fragment 分流：RK3566/3568
        叠 panfrost.config，RK3588 叠 rk3588_panthor.config 切 mainline panthor。"""
        rk3588 = _load_soc_config("rk3588")
        rk3566 = _load_soc_config("rk3566")
        # repo / dts_dir / branch 全系一致（rkr5.1 统一）
        assert rk3588["kernel"]["repo"] == rk3566["kernel"]["repo"]
        assert rk3588["kernel"]["dts_dir"] == rk3566["kernel"]["dts_dir"]
        assert rk3588["kernel"]["branch"] == "linux-6.1-stan-rkr5.1"
        assert rk3588["kernel"]["branch"] == rk3566["kernel"]["branch"]
        # defconfig 形态按 GPU 驱动分流：RK3588 叠 case_insensitive_fix + panthor；
        # RK3566/3568 叠 panfrost。
        assert rk3588["kernel"]["defconfig"] == [
            "rockchip_linux_defconfig",
            "case_insensitive_fix.config",
            "rk3588_panthor.config",
        ]
        assert rk3566["kernel"]["defconfig"] == [
            "rockchip_linux_defconfig",
            "panfrost.config",
        ]

    def test_kernel_args_uart2(self):
        soc = _load_soc_config("rk3588")
        assert "ttyS2,1500000" in soc["boot"]["kernel_args"]

    def test_extra_firmware_mali_csf_source_kernel(self):
        """RK3588 / RK3588S 必须声明 mali-csf firmware（panthor 必需），
        通过 source="kernel" 从 BSP kernel src 内 vendor 的 blob 取，
        不依赖外部固件仓库。"""
        for soc_name in ("rk3588", "rk3588s"):
            soc = _load_soc_config(soc_name)
            extra = soc.get("rootfs", {}).get("extra_firmware", [])
            mali = next((e for e in extra if e.get("name") == "mali-csf"), None)
            assert mali is not None, f"{soc_name} 缺 mali-csf extra_firmware"
            assert mali["source"] == "kernel"
            assert mali["repo_subdir"] == "drivers/gpu/arm/bifrost"
            assert mali["files"] == ["mali_csffw.bin"]
            assert mali["dest"] == "lib/firmware/arm/mali/arch10.8"

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
