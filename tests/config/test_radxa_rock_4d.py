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
        # bootloader 走 prebuilt spi.img（不自编 u-boot）：repo/branch 沿用 SoC 层默认
        # （branch 对该板不参与构建，故 board 不再覆盖 → 继承 SoC v2026.01）。
        assert merged["bootloader"]["repo"] == "https://github.com/radxa/u-boot"
        assert merged["bootloader"]["branch"] == "next-dev-v2026.01"

    def test_board_uses_prebuilt_spi(self, merged):
        """RK3576 idbloader 须 boot_merger 装配含 rk3576_boost；flange 通用 mkimage
        rksd 路径缺 boost → SPL 环境不全、u-boot 读 UFS 崩（6 次上板 + 构建链路审计
        坐实，与 BL31/OPTEE/u-boot 分支均无关）。故锁 radxa bsp 预编整体 spi.img、
        不自编 u-boot；详见 design Decision 6。"""
        bl = merged["bootloader"]
        # 构建期从 radxa 官方下载（url+sha256，不入库 16MB blob）
        prebuilt = bl["prebuilt_spi_image"]
        assert prebuilt["url"].endswith("rock-4d-spi-flash-image.img")
        assert len(prebuilt["sha256"]) == 64
        # 不自编 → board 不带自编 SPL / BL31 覆盖键；defconfig 仅继承 SoC generic
        # （prebuilt 路径不使用），未被 board 覆盖成板级 rock-4d-spi。
        assert bl.get("defconfig") == "rk3576_defconfig"
        assert "idbloader_spl" not in bl
        assert "bl31_override" not in bl

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

    def test_spi_firmware_via_prebuilt_not_selfsynth(self, merged):
        # SPI 启动固件来源 = prebuilt_spi_image（见 test_board_uses_prebuilt_spi），
        # 不走自编合成；故 board 不设 flash_spi_loader（flash.py prebuilt 分支优先于
        # flash_spi_loader 的 build_spi_image 自编合成路径）。
        assert "flash_spi_loader" not in merged
        # UFS 刷写走 upgrade_tool di -p（flash_storage="SATA"）。
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
