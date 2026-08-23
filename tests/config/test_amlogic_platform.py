"""amlogic 平台配置 + s905d3 SoC 自动发现与字段完整性。

覆盖 amlogic-platform spec 中以下 requirements：
- amlogic 平台模块自动发现（platform 层）
- amlogic 平台 SoC 配置自动发现（s905d3）
- s905d3 SoC 配置完整声明（mainline u-boot / linux / LibreELEC fip / fastboot fragment / g12a 工具）
- 与现有 rockchip / allwinnera733 平台互不污染
"""

from __future__ import annotations

import pytest

from builder.config.registry import (
    _discover_platform_configs,
    _discover_soc_configs,
    _load_platform_config,
    _load_soc_config,
)
from builder.paths import PROJECT_ROOT


REQUIRED_PLATFORM_FIELDS = (
    "vendor", "flash_tool", "arch", "products", "variants",
    "rootfs", "recovery",
)

REQUIRED_SOC_TOP_FIELDS = (
    "platform", "soc", "arch", "vendor",
    "repos", "bootloader", "kernel", "boot", "partitions", "rootfs",
)


class TestAmlogicPlatformDiscovery:
    """amlogic 平台层自动发现与字段完整性。"""

    def test_discovered_in_platform_map(self):
        configs = _discover_platform_configs(PROJECT_ROOT)
        assert "amlogic" in configs
        assert configs["amlogic"].endswith(
            "components/platform/amlogic/config.py"
        )

    def test_load_platform_returns_dict(self):
        cfg = _load_platform_config("amlogic", PROJECT_ROOT)
        assert isinstance(cfg, dict)
        for k in REQUIRED_PLATFORM_FIELDS:
            assert k in cfg, f"PLATFORM 缺字段: {k}"

    def test_platform_vendor_is_amlogic(self):
        cfg = _load_platform_config("amlogic", PROJECT_ROOT)
        assert cfg["vendor"] == "amlogic"
        assert cfg["arch"] == "aarch64"

    def test_platform_flash_tool_is_fastboot(self):
        """flash 主流程通过 fastboot；pre_flash 阶段才用 pyamlboot。"""
        cfg = _load_platform_config("amlogic", PROJECT_ROOT)
        assert cfg["flash_tool"] == "fastboot"

    def test_platform_does_not_declare_wifi_firmware_pkg(self):
        """平台层不挂 WiFi/BT 通用固件包 —— 不同 amlogic 板的 WiFi/BT chip
        各异（VIM3L 是 BCM4359/AP6398S，其他板可能 RTL 等），无法共享。
        Ubuntu 24.04 也没有 Debian 切片包 firmware-brcm80211（实测）。
        各 board 在 +extra_firmware 自行声明固件来源。
        """
        cfg = _load_platform_config("amlogic", PROJECT_ROOT)
        plus_pkgs = cfg.get("rootfs", {}).get("+packages", [])
        assert "firmware-brcm80211" not in plus_pkgs
        # 平台层 rootfs 不应有任何 +packages（custom_packages 例外）
        assert plus_pkgs == [] or "+packages" not in cfg["rootfs"]

    def test_platform_recovery_enabled_by_default(self):
        cfg = _load_platform_config("amlogic", PROJECT_ROOT)
        assert cfg["recovery"]["enabled"] is True
        assert cfg["recovery"]["transport"] == "adb"


class TestS905D3SoCDiscovery:
    """s905d3 SoC 自动发现与字段完整性。"""

    def test_discovered_in_soc_map(self):
        configs = _discover_soc_configs(PROJECT_ROOT)
        assert "s905d3" in configs
        assert configs["s905d3"].endswith(
            "components/platform/amlogic/s905d3/config.py"
        )

    def test_load_soc_returns_dict(self):
        cfg = _load_soc_config("s905d3", PROJECT_ROOT)
        assert isinstance(cfg, dict)
        for k in REQUIRED_SOC_TOP_FIELDS:
            assert k in cfg, f"SOC 缺字段: {k}"

    def test_soc_identity_fields(self):
        cfg = _load_soc_config("s905d3", PROJECT_ROOT)
        assert cfg["platform"] == "amlogic"
        assert cfg["soc"] == "s905d3"
        assert cfg["arch"] == "aarch64"
        assert cfg["vendor"] == "amlogic"

    def test_soc_declares_three_repos(self):
        cfg = _load_soc_config("s905d3", PROJECT_ROOT)
        for k in ("u-boot", "linux", "amlogic-boot-fip"):
            assert k in cfg["repos"], f"repos 缺 {k}"

    def test_uboot_repo_is_mainline(self):
        cfg = _load_soc_config("s905d3", PROJECT_ROOT)
        ub = cfg["repos"]["u-boot"]
        assert ub["repo"] == "https://github.com/u-boot/u-boot.git"
        assert ub["branch"] == "v2024.10"

    def test_linux_repo_is_mainline_lts_6_12(self):
        cfg = _load_soc_config("s905d3", PROJECT_ROOT)
        lin = cfg["repos"]["linux"]
        assert lin["repo"] == "https://github.com/torvalds/linux.git"
        assert lin["branch"] == "v6.12"

    def test_fip_repo_is_libreelec(self):
        cfg = _load_soc_config("s905d3", PROJECT_ROOT)
        fip = cfg["repos"]["amlogic-boot-fip"]
        assert fip["repo"] == "https://github.com/LibreELEC/amlogic-boot-fip.git"

    def test_bootloader_defconfig_is_list_with_fastboot_fragment(self):
        """defconfig 必须是 list 形式（base + fragment 合并），含 fastboot fragment。

        mainline khadas-vim3l_defconfig 默认只开 DFU 不开 fastboot；flange 的
        flash 流程需要 fastboot，所以 SoC 层挂 fragment 启用。
        """
        cfg = _load_soc_config("s905d3", PROJECT_ROOT)
        dc = cfg["bootloader"]["defconfig"]
        assert isinstance(dc, list)
        assert dc[0] == "khadas-vim3l_defconfig"
        # fragment 名含 fastboot 即可，具体名以 SoC config 为准
        assert any("fastboot" in x for x in dc[1:]), \
            f"defconfig list 中找不到 fastboot fragment: {dc}"

    def test_bootloader_fip_tool_is_g12a(self):
        """SM1 family 复用 G12A 工具，非 aml_encrypt_sm1（LibreELEC 不存在该名称）。"""
        cfg = _load_soc_config("s905d3", PROJECT_ROOT)
        assert cfg["bootloader"]["fip_tool"] == "aml_encrypt_g12a"
        assert cfg["bootloader"]["fip_family_inc"] == "g12a.inc"

    def test_bootloader_does_not_declare_board_dir(self):
        """fip_board_dir 是 board 粒度字段，不应出现在 SoC 层。"""
        cfg = _load_soc_config("s905d3", PROJECT_ROOT)
        assert "fip_board_dir" not in cfg["bootloader"]

    def test_kernel_dts_dir_is_amlogic(self):
        cfg = _load_soc_config("s905d3", PROJECT_ROOT)
        assert cfg["kernel"]["dts_dir"] == "amlogic"
        assert cfg["kernel"]["defconfig"] == [
            "defconfig", "CONFIG_DRM_GUD=y",
        ]

    def test_kernel_args_includes_ttyaml0(self):
        cfg = _load_soc_config("s905d3", PROJECT_ROOT)
        args = cfg["boot"]["kernel_args"]
        assert "ttyAML0" in args
        assert "115200" in args

    def test_partitions_layout_no_raw_boot(self):
        """与 rockchip 同形：boot / recovery / rootfs 三个 GPT 分区，
        无 idbloader/uboot raw（因 Amlogic BootROM 走 hw boot0 不读 user area）。
        """
        cfg = _load_soc_config("s905d3", PROJECT_ROOT)
        names = [e["name"] for e in cfg["partitions"]["entries"]]
        assert names == ["boot", "recovery", "rootfs"]
        # 所有 entry 都应是 ext4，无 raw 类型
        for e in cfg["partitions"]["entries"]:
            assert e["type"] == "ext4", f"{e['name']} 非 ext4: {e['type']}"

    def test_partitions_rootfs_grows(self):
        cfg = _load_soc_config("s905d3", PROJECT_ROOT)
        rootfs_entry = next(
            e for e in cfg["partitions"]["entries"] if e["name"] == "rootfs"
        )
        assert rootfs_entry["size"] == "remaining"
        assert rootfs_entry["grow_on_first_boot"] is True


class TestExistingPlatformsUnaffected:
    """平台发现覆盖当前全部已注册平台。"""

    def test_rockchip_platform_intact(self):
        cfg = _load_platform_config("rockchip", PROJECT_ROOT)
        assert cfg["vendor"] == "rockchip"

    def test_allwinnera733_platform_intact(self):
        cfg = _load_platform_config("allwinnera733", PROJECT_ROOT)
        assert cfg["vendor"] == "allwinnera733"

    def test_rk3566_soc_intact(self):
        """rk3566 仍能被发现，关键字段不变（mkimage_chip='rk3568'，与 rockchip-platform spec 对齐）。"""
        cfg = _load_soc_config("rk3566", PROJECT_ROOT)
        assert cfg["platform"] == "rockchip"
        assert cfg["rkbin"]["mkimage_chip"] == "rk3568"

    def test_a733_soc_intact(self):
        cfg = _load_soc_config("a733", PROJECT_ROOT)
        assert cfg["platform"] == "allwinnera733"

    def test_all_platforms_discovered(self):
        platforms = _discover_platform_configs(PROJECT_ROOT)
        assert set(platforms.keys()) == {
            "rockchip", "allwinnera733", "amlogic", "qualcommqcs6490",
            "qualcommsc8280xp",
        }

    def test_no_cross_pollution_in_soc_map(self):
        """amlogic SoC 不应出现在 rockchip / allwinnera733 平台下。"""
        socs = _discover_soc_configs(PROJECT_ROOT)
        # amlogic SoC 路径应在 amlogic 子目录下
        assert "components/platform/amlogic/" in socs["s905d3"]
        # rockchip / a733 SoC 路径不在 amlogic 下
        for soc_name in ("rk3566", "rk3588", "a733"):
            assert "components/platform/amlogic/" not in socs[soc_name]
