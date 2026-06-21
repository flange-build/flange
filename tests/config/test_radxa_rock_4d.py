"""Radxa ROCK 4D（RK3576 / UFS）板级配置三层合并验证。

覆盖 rockchip-platform spec "Rockchip 平台支持 Radxa ROCK 4D 板级配置（UFS）"
requirement。
"""

from __future__ import annotations

import pytest

from builder.config.query import get_valid_targets
from builder.config.registry import (
    _load_soc_config,
    discover_boards,
    get_board_config,
    resolve_config,
)


@pytest.fixture(scope="module")
def boards():
    return discover_boards()


class TestROCK4DBoardDiscovery:
    def test_discovered(self, boards):
        assert "radxa-rock-4d" in boards

    def test_board_identity_fields(self, boards):
        cfg = boards["radxa-rock-4d"]
        assert cfg["board"] == "radxa-rock-4d"
        assert cfg["soc"] == "rk3576"
        assert cfg["platform"] == "rockchip"
        assert cfg["kernel"]["dts"] == "rk3576-rock-4d"


class TestROCK4DMergedConfig:
    @pytest.fixture()
    def merged(self, boards):
        return get_board_config("radxa-rock-4d", boards=boards)

    def test_platform_layer_inherited(self, merged):
        assert merged["vendor"] == "rockchip"
        assert merged["flash_tool"] == "upgrade_tool"
        assert merged["arch"] == "aarch64"

    def test_soc_layer_inherited(self, merged):
        assert merged["soc"] == "rk3576"
        assert merged["rkbin"]["mkimage_chip"] == "rk3576"
        assert merged["kernel"]["branch"] == "linux-6.1-stan-rkr5.1"
        # 自编 u-boot.itb：repo + branch 沿用 SoC 层默认（与其他 rockchip SoC 统一
        # next-dev-v2026.01）。
        assert merged["bootloader"]["repo"] == "https://github.com/radxa/u-boot"
        assert merged["bootloader"]["branch"] == "next-dev-v2026.01"
        # RK3576 idbloader 经 boot_merger（SoC 级声明，board 继承）。
        assert merged["bootloader"]["idbloader_method"] == "boot_merger"

    def test_board_selfbuilds_spi(self, merged):
        """flange 自编 spi.img：idbloader 经 boot_merger 装配（含 rk3576_boost，SoC 层
        idbloader_method），u-boot proper 用**对板** defconfig
        rock-4d-spi-rk3576_defconfig（DT=rk3576-rock-4d-spi，含 SPI NOR pinmux + 板级
        节点）—— 修「错板」proper（SoC generic rk3576_defconfig 的 DT 是 rk3576-evb）。
        不下载 prebuilt。详见 design Decision 1/5。"""
        bl = merged["bootloader"]
        # 不再下载 prebuilt 整体 spi.img
        assert "prebuilt_spi_image" not in bl
        # board 覆盖对板 defconfig（修「错板」proper）
        assert bl["defconfig"] == "rock-4d-spi-rk3576_defconfig"
        # idbloader 经 boot_merger（SoC 层继承），不自编 SPL
        assert bl["idbloader_method"] == "boot_merger"
        assert "idbloader_spl" not in bl

    def test_partitions_sector_size_4096(self, merged):
        # UFS 强制 4K 逻辑块（Radxa 要求）；board 仅覆盖 sector_size，
        # entries 沿用 SoC 层。
        assert merged["partitions"]["sector_size"] == 4096

    def test_ufs_partitions_os_only(self, merged):
        names = [e["name"] for e in merged["partitions"]["entries"]]
        # 架构 A2：bootloader 全在 SPI，UFS 只放 OS
        assert "idbloader" not in names   # 512 格式，写 UFS 有害
        assert "uboot" not in names       # u-boot.itb 在 SPI（@8MiB）
        for required in ("boot", "recovery", "rootfs"):
            assert required in names

    def test_spi_firmware_via_selfbuild(self, merged):
        # SPI 启动固件来源 = 自编 spi.img：board 设 flash_spi_loader=True →
        # flash.py 经 build_spi_image 合成 idbloader + u-boot.itb（不走 prebuilt 下载）。
        assert merged.get("flash_spi_loader") is True
        assert "prebuilt_spi_image" not in merged.get("bootloader", {})
        # UFS 刷写仍走 upgrade_tool di -p（flash_storage="SATA"）。
        assert merged.get("flash_storage") == "SATA"


class TestROCK4DDoesNotPolluteSoC:
    """board 层 UFS 覆盖不得改动 SoC 层 eMMC 默认布局。"""

    def test_soc_layer_stays_512(self):
        soc = _load_soc_config("rk3576")
        # SoC 层不声明 sector_size（即默认 512 eMMC），或显式 512
        assert soc["partitions"].get("sector_size", 512) == 512


class TestROCK4DLunchTargets:
    def test_targets_include_default_debug_and_release(self, boards):
        targets = set(get_valid_targets(boards=boards))
        assert "radxa-rock-4d-default-debug" in targets
        assert "radxa-rock-4d-default-release" in targets


class TestROCK4DWifiAIC8800:
    """板载 WiFi/BT 走 AIC8800D80 USB combo，与其他 radxa 板（rock5c-lite /
    cubie-a7z/a7a）同一 radxa-pkg/aic8800 OOT 路线。"""

    @pytest.fixture()
    def cfg(self, boards):
        return resolve_config("radxa-rock-4d", "default", "release", boards=boards)

    def test_aic8800_oot_source(self, cfg):
        assert "aic8800" in cfg["kernel"].get("oot_sources", {})

    def test_wifi_and_bt_oot_modules(self, cfg):
        labels = " ".join(m.get("label", "") for m in cfg["kernel"].get("oot_modules", []))
        assert "aic8800" in labels  # WiFi: aic_load_fw + aic8800_fdrv
        assert "aic_btusb" in labels  # BT

    def test_aic8800_firmware_deployed(self, cfg):
        names = [e["name"] for e in cfg["rootfs"].get("extra_firmware", [])]
        assert "aic8800-d80" in names
