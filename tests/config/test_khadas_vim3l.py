"""Khadas VIM3L 板级配置三层合并验证。

覆盖 amlogic-platform spec 中 "khadas-vim3l 板级配置完整" 与
"khadas-vim3l Wi-Fi/BT 固件部署" 两条 requirement。

测试形态对齐 tests/config/test_radxa_rock5b.py（rk3588 第一板范例）：
仅依赖 discover_boards / get_board_config / get_valid_targets 三个公开 API，
不 mock 内部细节。
"""

from __future__ import annotations

import pytest

from builder.config.query import get_valid_targets
from builder.config.registry import discover_boards, get_board_config


@pytest.fixture(scope="module")
def boards():
    return discover_boards()


class TestVIM3LBoardDiscovery:
    """khadas-vim3l 板被自动发现且字段最小完整。"""

    def test_discovered(self, boards):
        assert "khadas-vim3l" in boards

    def test_board_identity_fields(self, boards):
        cfg = boards["khadas-vim3l"]
        assert cfg["board"] == "khadas-vim3l"
        assert cfg["soc"] == "s905d3"
        assert cfg["platform"] == "amlogic"
        assert cfg["kernel"]["dts"] == "meson-sm1-khadas-vim3l"


class TestVIM3LMergedConfig:
    """三层合并（platform → SoC → board）后字段完整且取值正确。"""

    @pytest.fixture()
    def merged(self, boards):
        return get_board_config("khadas-vim3l", boards=boards)

    def test_platform_layer_fields(self, merged):
        """合并后保留 platform 层字段。"""
        assert merged["vendor"] == "amlogic"
        assert merged["flash_tool"] == "fastboot"
        assert merged["arch"] == "aarch64"

    def test_soc_layer_fields(self, merged):
        """合并后保留 SoC 层字段（VIM3L 不覆盖 fip_tool / dts_dir / kernel_args，
        全部沿用 SoC s905d3 的 mainline 取值）。"""
        assert merged["soc"] == "s905d3"
        # 三个命名仓库全部到位
        assert merged["repos"]["u-boot"]["branch"] == "v2024.10"
        assert merged["repos"]["linux"]["branch"] == "v6.12"
        assert (
            merged["repos"]["amlogic-boot-fip"]["repo"]
            == "https://github.com/LibreELEC/amlogic-boot-fip.git"
        )
        # bootloader：base defconfig + fastboot fragment（SoC 层 list 形态）
        assert merged["bootloader"]["defconfig"] == [
            "khadas-vim3l_defconfig",
            "flange_fastboot.config",
        ]
        # SM1 family 复用 G12A 工具链
        assert merged["bootloader"]["fip_tool"] == "aml_encrypt_g12a"
        assert merged["bootloader"]["fip_family_inc"] == "g12a.inc"
        # kernel：mainline arm64 generic defconfig，dts_dir 由 SoC 提供
        assert merged["kernel"]["defconfig"] == "defconfig"
        assert merged["kernel"]["dts_dir"] == "amlogic"

    def test_board_layer_fields(self, merged):
        """合并后保留 board 层字段（board 名 / DTS / fip_board_dir）。"""
        assert merged["board"] == "khadas-vim3l"
        assert merged["kernel"]["dts"] == "meson-sm1-khadas-vim3l"
        assert merged["bootloader"]["fip_board_dir"] == "khadas-vim3l"

    def test_kernel_args_ttyaml0(self, merged):
        """console=ttyAML0 来自 SoC 层 boot.kernel_args。"""
        args = merged["boot"]["kernel_args"]
        assert "console=ttyAML0,115200n8" in args
        assert "earlycon" in args

    def test_partitions_three_entries(self, merged):
        """与 SoC 层声明一致：boot / recovery / rootfs，无 idbloader/uboot raw
        （Amlogic eMMC 启动靠 hw boot0，不在 user area GPT 内）。"""
        names = [e["name"] for e in merged["partitions"]["entries"]]
        assert names == ["boot", "recovery", "rootfs"]

    def test_partitions_rootfs_grows(self, merged):
        rootfs_entry = next(
            e for e in merged["partitions"]["entries"] if e["name"] == "rootfs"
        )
        assert rootfs_entry["size"] == "remaining"
        assert rootfs_entry["grow_on_first_boot"] is True

    def test_rootfs_url_ubuntu_base_24_04(self, merged):
        """rootfs.url 来自 SoC 层（ubuntu-base 24.04 arm64）。"""
        assert "ubuntu-base-24.04" in merged["rootfs"]["url"]
        assert "arm64" in merged["rootfs"]["url"]

    def test_rootfs_custom_packages_inherits_platform(self, merged):
        """platform 层的 custom_packages（adbd / recoveryctl /
        flange-rootfs-grow）应直接继承到 board，没有 board 覆盖。"""
        custom = merged["rootfs"]["custom_packages"]
        assert "adbd" in custom
        assert "recoveryctl" in custom
        assert "flange-rootfs-grow" in custom

    def test_rootfs_board_packages_include_bluez(self, merged):
        """board 层 +packages 含 bluez（btattach + bluetoothd 来源）。

        merge.py 的 +key 追加语义经 deep_merge → resolve_conditions 两阶段处理，
        本断言只验证 board 层 +packages 这条声明在合并后仍可见。具体进 packages
        list 的链路由 resolve_config + _expand_rootfs_package_sets 完成。
        """
        # +packages 形态在 deep_merge 阶段保留，等到 resolve_conditions 才扁平化。
        plus_pkgs = merged["rootfs"].get("+packages", [])
        assert "bluez" in plus_pkgs

    def test_rootfs_extra_firmware_ap6398s_override(self, merged):
        """+extra_firmware 含 khadas-fenix-ap6398s 板级覆盖；两件文件 rename
        到 mainline brcmfmac/btbcm 加载路径上的通用名。"""
        extras = merged["rootfs"]["+extra_firmware"]
        names = [e["name"] for e in extras]
        assert names == ["khadas-fenix-ap6398s"], (
            f"VIM3L 应仅声明一个板级 +extra_firmware 条目；实际: {names}"
        )

        entry = extras[0]
        assert entry["repo"] == "https://github.com/khadas/fenix.git"
        assert entry["branch"] == "master"
        assert entry["repo_subdir"] == "archives/hwpacks/wlan-firmware/brcm"
        assert entry["dest"] == "lib/firmware/brcm"

        # files 必须含 NVRAM + BT patchram 两件覆盖，源名带 _ap6398s 后缀，
        # 落地名是 brcmfmac/btbcm 标准通用名（覆盖 firmware-brcm80211 包默认）。
        files = {f["src"]: f["dest"] for f in entry["files"]}
        assert files == {
            "brcmfmac4359-sdio_ap6398s.txt": "brcmfmac4359-sdio.txt",
            "BCM4359C0_ap6398s.hcd": "BCM4359C0.hcd",
        }


class TestVIM3LOverlayFiles:
    """板级 overlay 文件存在且内容正确。"""

    def test_hostname_overlay_present(self):
        from builder.paths import COMPONENTS_ROOT
        path = (
            COMPONENTS_ROOT
            / "board" / "khadas-vim3l" / "overlay" / "etc" / "hostname"
        )
        assert path.is_file(), f"缺少 hostname overlay: {path}"
        # 允许尾换行（与 rock5b 同形）
        assert path.read_text().strip() == "khadas-vim3l"

    def test_bluetooth_service_overlay_present(self):
        """bluetooth-vim3l.service 单元存在且声明正确的 ExecStart。"""
        from builder.paths import COMPONENTS_ROOT
        path = (
            COMPONENTS_ROOT
            / "board" / "khadas-vim3l"
            / "overlay" / "etc" / "systemd" / "system"
            / "bluetooth-vim3l.service"
        )
        assert path.is_file(), f"缺少 bluetooth-vim3l.service: {path}"
        content = path.read_text()
        # btattach 命令行：-B 指定 UART，-P bcm 选择 Broadcom HCI 协议（btbcm 接管 patchram）
        assert "ExecStart=/usr/bin/btattach -B /dev/ttyAML6 -P bcm" in content
        # 时序：在 bluetooth.target 之前 attach
        assert "Before=bluetooth.target" in content
        # 安装目标：multi-user.target，与 bluez 的 bluetooth.service 同 enable 时机
        assert "WantedBy=multi-user.target" in content


class TestVIM3LLunchTargets:
    """khadas-vim3l lunch target 自动出现在可用目标列表。"""

    def test_targets_include_default_debug_and_release(self, boards):
        targets = set(get_valid_targets(boards=boards))
        assert "khadas-vim3l-default-debug" in targets
        assert "khadas-vim3l-default-release" in targets
