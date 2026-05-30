"""amlogic s905y2 SoC 自动发现与字段完整性。

覆盖 amlogic-platform spec 中 "s905y2 SoC 配置完整声明" requirement 的
三条 scenario：
- 自动发现 s905y2 SoC
- s905y2 使用 Radxa Zero U-Boot 与 G12A FIP 工具
- s905y2 使用 mainline Radxa Zero DTS

测试形态对齐 tests/config/test_amlogic_platform.py 的 TestS905D3SoCDiscovery：
仅依赖 _discover_soc_configs / _load_soc_config 两个内部 API。
"""

from __future__ import annotations

import pytest

from builder.config.registry import (
    _discover_soc_configs,
    _load_soc_config,
)
from builder.paths import COMPONENTS_ROOT, PROJECT_ROOT


REQUIRED_SOC_TOP_FIELDS = (
    "platform", "soc", "arch", "vendor",
    "repos", "bootloader", "kernel", "boot", "partitions", "rootfs",
)


class TestS905Y2SoCDiscovery:
    """s905y2 SoC 自动发现与字段完整性。"""

    def test_discovered_in_soc_map(self):
        configs = _discover_soc_configs(PROJECT_ROOT)
        assert "s905y2" in configs
        assert configs["s905y2"].endswith(
            "components/platform/amlogic/s905y2/config.py"
        )

    def test_load_soc_returns_dict(self):
        cfg = _load_soc_config("s905y2", PROJECT_ROOT)
        assert isinstance(cfg, dict)
        for k in REQUIRED_SOC_TOP_FIELDS:
            assert k in cfg, f"SOC 缺字段: {k}"

    def test_soc_identity_fields(self):
        cfg = _load_soc_config("s905y2", PROJECT_ROOT)
        assert cfg["platform"] == "amlogic"
        assert cfg["soc"] == "s905y2"
        assert cfg["arch"] == "aarch64"
        assert cfg["vendor"] == "amlogic"

    def test_soc_declares_three_repos(self):
        cfg = _load_soc_config("s905y2", PROJECT_ROOT)
        for k in ("u-boot", "linux", "amlogic-boot-fip"):
            assert k in cfg["repos"], f"repos 缺 {k}"

    def test_uboot_repo_is_mainline(self):
        cfg = _load_soc_config("s905y2", PROJECT_ROOT)
        ub = cfg["repos"]["u-boot"]
        assert ub["repo"] == "https://github.com/u-boot/u-boot.git"
        assert ub["branch"] == "v2024.10"

    def test_linux_repo_is_mainline_lts_6_12(self):
        cfg = _load_soc_config("s905y2", PROJECT_ROOT)
        lin = cfg["repos"]["linux"]
        assert lin["repo"] == "https://github.com/torvalds/linux.git"
        assert lin["branch"] == "v6.12"

    def test_fip_repo_is_libreelec(self):
        cfg = _load_soc_config("s905y2", PROJECT_ROOT)
        fip = cfg["repos"]["amlogic-boot-fip"]
        assert fip["repo"] == "https://github.com/LibreELEC/amlogic-boot-fip.git"

    def test_bootloader_defconfig_is_list_with_radxa_zero_and_fastboot(self):
        """defconfig 必须是 list（base + fragment 合并）：先 radxa-zero_defconfig，
        再叠加 fastboot fragment。

        mainline radxa-zero_defconfig 默认只开 DFU_RAM 不开 fastboot；flange 的
        flash 流程需要 fastboot，所以 SoC 层挂 fragment 启用。
        """
        cfg = _load_soc_config("s905y2", PROJECT_ROOT)
        dc = cfg["bootloader"]["defconfig"]
        assert isinstance(dc, list)
        assert dc[0] == "radxa-zero_defconfig"
        assert any("fastboot" in x for x in dc[1:]), \
            f"defconfig list 中找不到 fastboot fragment: {dc}"

    def test_fastboot_fragment_file_exists(self):
        """fragment 文件必须实际存在于 s905y2/patches/bootloader/，否则
        AmlogicBootloaderBuilder._stage_fragments 会 fail-fast。"""
        cfg = _load_soc_config("s905y2", PROJECT_ROOT)
        dc = cfg["bootloader"]["defconfig"]
        fragment = next(x for x in dc[1:] if x.endswith(".config"))
        path = (
            COMPONENTS_ROOT / "platform" / "amlogic" / "s905y2"
            / "patches" / "bootloader" / fragment
        )
        assert path.is_file(), f"缺少 fastboot fragment: {path}"
        text = path.read_text()
        # spec 列出的 fastboot 关键开关
        assert "CONFIG_USB_FUNCTION_FASTBOOT=y" in text
        assert "CONFIG_FASTBOOT_FLASH=y" in text
        assert "CONFIG_FASTBOOT_MMC_BOOT_SUPPORT=y" in text
        assert "CONFIG_FASTBOOT_CMD_OEM_FORMAT=y" in text
        # PREBOOT 自动进 fastboot
        assert "CONFIG_USE_PREBOOT=y" in text
        assert "fastboot usb 0" in text

    def test_fastboot_fragment_partitions_env_excludes_recovery(self):
        """task 2.3：partitions env 只含 boot 与 rootfs，不含 recovery
        （Radxa Zero 首版关闭 recovery）。"""
        path = (
            COMPONENTS_ROOT / "platform" / "amlogic" / "s905y2"
            / "patches" / "bootloader" / "flange_fastboot.config"
        )
        text = path.read_text()
        preboot = next(
            ln for ln in text.splitlines()
            if ln.startswith("CONFIG_PREBOOT=")
        )
        assert "name=boot" in preboot
        assert "name=rootfs" in preboot
        assert "recovery" not in preboot

    def test_fastboot_fragment_mmc_dev_is_emmc(self):
        """task 2.3：CONFIG_FASTBOOT_FLASH_MMC_DEV 指向 eMMC（G12A
        sd_emmc_c=mmc2 标准拓扑）。"""
        path = (
            COMPONENTS_ROOT / "platform" / "amlogic" / "s905y2"
            / "patches" / "bootloader" / "flange_fastboot.config"
        )
        text = path.read_text()
        assert "CONFIG_FASTBOOT_FLASH_MMC_DEV=2" in text

    def test_bootloader_fip_tool_is_g12a(self):
        """S905Y2 是 G12A native，加密工具即 aml_encrypt_g12a。"""
        cfg = _load_soc_config("s905y2", PROJECT_ROOT)
        assert cfg["bootloader"]["fip_tool"] == "aml_encrypt_g12a"
        assert cfg["bootloader"]["fip_family_inc"] == "g12a.inc"

    def test_bootloader_does_not_declare_board_dir(self):
        """fip_board_dir 是 board 粒度字段，不应出现在 SoC 层。"""
        cfg = _load_soc_config("s905y2", PROJECT_ROOT)
        assert "fip_board_dir" not in cfg["bootloader"]

    def test_kernel_dts_dir_is_amlogic(self):
        cfg = _load_soc_config("s905y2", PROJECT_ROOT)
        assert cfg["kernel"]["dts_dir"] == "amlogic"
        assert cfg["kernel"]["defconfig"] == "defconfig"

    def test_kernel_args_includes_ttyaml0(self):
        cfg = _load_soc_config("s905y2", PROJECT_ROOT)
        args = cfg["boot"]["kernel_args"]
        assert "console=ttyAML0,115200" in args
        assert "earlycon" in args

    def test_partitions_rootfs_grows(self):
        cfg = _load_soc_config("s905y2", PROJECT_ROOT)
        rootfs_entry = next(
            e for e in cfg["partitions"]["entries"] if e["name"] == "rootfs"
        )
        assert rootfs_entry["size"] == "remaining"
        assert rootfs_entry["grow_on_first_boot"] is True

    def test_partitions_no_raw_boot(self):
        """与 s905d3 同形：所有 SoC 层 entry 为 ext4，无 idbloader/uboot raw
        （Amlogic BootROM 走 hw boot0 不读 user area）。"""
        cfg = _load_soc_config("s905y2", PROJECT_ROOT)
        for e in cfg["partitions"]["entries"]:
            assert e["type"] == "ext4", f"{e['name']} 非 ext4: {e['type']}"


class TestS905D3Unaffected:
    """新增 s905y2 不污染既有 s905d3。"""

    def test_s905d3_intact(self):
        cfg = _load_soc_config("s905d3", PROJECT_ROOT)
        assert cfg["platform"] == "amlogic"
        assert cfg["soc"] == "s905d3"
        assert cfg["bootloader"]["defconfig"][0] == "khadas-vim3l_defconfig"

    def test_both_amlogic_socs_under_amlogic(self):
        socs = _discover_soc_configs(PROJECT_ROOT)
        assert "components/platform/amlogic/" in socs["s905d3"]
        assert "components/platform/amlogic/" in socs["s905y2"]
