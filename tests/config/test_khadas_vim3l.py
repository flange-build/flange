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
        # kernel：mainline arm64 generic defconfig + USB GUD；board 层显式追加
        # 网络协议栈与 TUN（网络隧道）支持，dts_dir 由 SoC 提供。
        assert merged["kernel"]["defconfig"] == [
            "defconfig", "CONFIG_DRM_GUD=y", "CONFIG_NET=y", "CONFIG_TUN=y",
        ]
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

    def test_recovery_disabled(self, merged):
        """VIM3L 板首版不交付 recovery 维护系统，board 层 enabled=False。"""
        assert merged["recovery"]["enabled"] is False

    def test_partitions_three_entries(self, merged):
        """board 层覆盖 SoC 分区布局（deep_merge 对 list 是替换语义）：
        bootloader (raw 占位，hw boot0 → fastboot 路由) + boot + rootfs；
        无 recovery（VIM3L 关 enabled，省 512MB 给 rootfs）。
        """
        names = [e["name"] for e in merged["partitions"]["entries"]]
        assert names == ["bootloader", "boot", "rootfs"], (
            f"VIM3L 应为 bootloader + boot + rootfs；实际: {names}"
        )

    def test_bootloader_is_raw_partition(self, merged):
        """bootloader 类型必须是 raw —— image.py GPT 写入时跳过 raw 类型
        （Amlogic BootROM 走 mmc1 hw boot0 而非 user area），仅靠该 entry
        让 FlashConfigGenerator 把 bootloader 纳入 flash-config，fastboot
        flash bootloader 路由到 hw boot0。"""
        entries = merged["partitions"]["entries"]
        bl = next(e for e in entries if e["name"] == "bootloader")
        assert bl["type"] == "raw"

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

        # files 必须含 WiFi 固件 + NVRAM + BT patchram 三件套，源名带
        # _ap6398s 后缀（Khadas 为 VIM3L 上 BCM4359 模组的板级调校版），
        # 落地名是 mainline brcmfmac/btbcm 标准通用名。Ubuntu 24.04 没有
        # firmware-brcm80211 切片包，整套都从 fenix 拉。
        files = {f["src"]: f["dest"] for f in entry["files"]}
        assert files == {
            "brcmfmac4359-sdio_ap6398s.bin": "brcmfmac4359-sdio.bin",
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


class TestVIM3LSpidev:
    """板私有 DT overlay：vim3l-spidev-spicc1 在 spicc1 上挂 spidev，
    覆盖 amlogic-platform spec "khadas-vim3l SPI 用户态访问" requirement。
    """

    @pytest.fixture()
    def merged(self, boards):
        return get_board_config("khadas-vim3l", boards=boards)

    def test_board_overlays_contains_spidev(self, merged):
        assert merged["boot"]["board_overlays"] == [
            "vim3l-spidev-spicc1.dtbo"
        ]

    def test_default_overlays_contains_spidev(self, merged):
        assert merged["boot"]["default_overlays"] == [
            "vim3l-spidev-spicc1.dtbo"
        ]

    def test_dtso_source_exists(self):
        from builder.paths import COMPONENTS_ROOT
        path = (
            COMPONENTS_ROOT
            / "board" / "khadas-vim3l"
            / "dtso" / "vim3l-spidev-spicc1.dtso"
        )
        assert path.is_file(), f"缺少 dtso 源文件: {path}"

    def test_dtso_content_contract(self):
        """dtso 必须满足 amlogic-platform spec 的 "dtso 源文件存在并满足契约"
        scenario 列出的全部 token：plugin 头 / &spicc1 / status okay /
        rohm,dh2228fv 借壳 / 24 MHz 上限。"""
        from builder.paths import COMPONENTS_ROOT
        path = (
            COMPONENTS_ROOT
            / "board" / "khadas-vim3l"
            / "dtso" / "vim3l-spidev-spicc1.dtso"
        )
        text = path.read_text()
        assert "/dts-v1/;" in text
        assert "/plugin/;" in text
        assert "&spicc1" in text
        assert 'status = "okay";' in text
        assert 'compatible = "rohm,dh2228fv";' in text
        assert "spi-max-frequency = <24000000>;" in text


class TestVIM3LLunchTargets:
    """khadas-vim3l lunch target 自动出现在可用目标列表。"""

    def test_targets_include_default_debug_and_release(self, boards):
        targets = set(get_valid_targets(boards=boards))
        assert "khadas-vim3l-default-debug" in targets
        assert "khadas-vim3l-default-release" in targets
