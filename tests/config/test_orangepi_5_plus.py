"""OrangePi 5 Plus 板级配置三层合并验证。

覆盖 rockchip-orangepi-5-plus spec 中的 board 字段、SoC 层不被覆盖、
RTL8852BE OOT 链路、HX8399-A DSI 屏 + GT911 触摸 board overlay、lunch target 自动生成
五项 requirement。WiFi/BT OOT 链路与 radxa-rock5b 逐字段等价（按值比较）。
"""

from __future__ import annotations

import pytest

from builder.config.query import get_valid_targets
from builder.config.registry import discover_boards, get_board_config, resolve_config


@pytest.fixture(scope="module")
def boards():
    return discover_boards()


class TestOrangePi5PlusBoardDiscovery:
    """OrangePi 5 Plus 板被自动发现且字段最小完整。"""

    def test_discovered(self, boards):
        assert "orangepi-5-plus" in boards

    def test_board_identity_fields(self, boards):
        cfg = boards["orangepi-5-plus"]
        assert cfg["board"] == "orangepi-5-plus"
        assert cfg["soc"] == "rk3588"
        assert cfg["platform"] == "rockchip"
        assert cfg["kernel"]["dts"] == "rk3588-orangepi-5-plus"


class TestOrangePi5PlusMergedConfig:
    """三层合并（platform → SoC → board）后字段完整且取值正确。"""

    @pytest.fixture()
    def merged(self, boards):
        return get_board_config("orangepi-5-plus", boards=boards)

    def test_platform_layer_fields(self, merged):
        """合并后保留 platform 层字段。"""
        assert merged["vendor"] == "rockchip"
        assert merged["flash_tool"] == "upgrade_tool"
        assert merged["arch"] == "aarch64"

    def test_soc_layer_bootloader_not_overridden(self, merged):
        """SoC 层 bootloader 字段不被 board 覆盖。"""
        assert merged["bootloader"]["repo"] == "https://github.com/radxa/u-boot"
        assert merged["bootloader"]["branch"] == "next-dev-v2026.01"
        assert merged["bootloader"]["defconfig"] == "rk3588_defconfig"

    def test_soc_layer_rkbin_not_overridden(self, merged):
        """SoC 层 rkbin.mkimage_chip / ini_prefix 不被 board 覆盖。"""
        assert merged["rkbin"]["mkimage_chip"] == "rk3588"
        assert merged["rkbin"]["ini_prefix"] == "RK3588"
        assert merged["rkbin"]["trust_ini_prefix"] == "RK3588"

    def test_soc_layer_kernel_not_overridden(self, merged):
        """SoC 层 kernel.branch 不被 board 覆盖；default product 下 defconfig
        list 仅含 SoC 四项（board 把 GOODIX 移到 +defconfig:wks55fhd001wct-bringup
        条件块，default 不命中）。"""
        assert merged["kernel"]["branch"] == "linux-6.1-stan-rkr5.1"
        assert merged["kernel"]["defconfig"] == [
            "rockchip_linux_defconfig",
            "case_insensitive_fix.config",
            "rk3588_panthor.config",
            "CONFIG_DRM_GUD=y",
        ]

    def test_kernel_goodix_only_on_bringup_product(self, boards):
        """board 通过 kernel.+defconfig:wks55fhd001wct-bringup 写 raw
        CONFIG_TOUCHSCREEN_GOODIX=y 启用 mainline drivers/input/touchscreen
        /goodix.c，匹配 dtso compatible="goodix,gt911" GT911 触摸节点（vendor
        BSP 默认 # CONFIG_TOUCHSCREEN_GOODIX is not set，必须 fragment 补）。
        Builder 把 raw 字符串聚合到动态 flange_inline.config 喂给 make。

        default product 是裸机不挂屏，不带 GOODIX 驱动；只有 wks55fhd001wct
        -bringup product（屏模组 panel=HX8399-A, touch=GT911）才条件追加。
        """
        cfg_default = resolve_config(
            "orangepi-5-plus", "default", "debug", boards=boards)
        assert "CONFIG_TOUCHSCREEN_GOODIX=y" not in cfg_default["kernel"]["defconfig"]
        cfg_bringup = resolve_config(
            "orangepi-5-plus", "wks55fhd001wct-bringup", "debug", boards=boards)
        assert "CONFIG_TOUCHSCREEN_GOODIX=y" in cfg_bringup["kernel"]["defconfig"]

    def test_board_layer_fields(self, merged):
        """合并后保留 board 层字段（board 名 / DTS）。"""
        assert merged["board"] == "orangepi-5-plus"
        assert merged["kernel"]["dts"] == "rk3588-orangepi-5-plus"

    def test_kernel_args_uart2_inherited(self, merged):
        """串口 console 沿用 SoC 层 UART2 1500000。"""
        assert "ttyS2,1500000" in merged["boot"]["kernel_args"]

    def test_partitions_5_entries_inherited(self, merged):
        """分区布局沿用 SoC 层 5 分区。"""
        names = [e["name"] for e in merged["partitions"]["entries"]]
        assert names == ["idbloader", "uboot", "boot", "recovery", "rootfs"]

    def test_extra_firmware_mali_csf_inherited(self, merged):
        """与 ROCK 5B 同源继承 SoC 层 mali-csf firmware 声明（panthor 驱动用）。"""
        extra = merged.get("rootfs", {}).get("extra_firmware", [])
        names = [e.get("name") for e in extra]
        assert "mali-csf" in names, (
            f"OrangePi 5 Plus merged config 应包含 mali-csf extra_firmware；实际: {names}")

    def test_board_overlays_hx8399a_gt911_bringup_only(self, boards):
        """HX8399-A 1080×1920 DSI 屏 + GT911 触摸 overlay 仅在
        wks55fhd001wct-bringup product 下加载；default 裸机不带这条 overlay。
        board_overlays 与 default_overlays 同步追加（dtbo 既要编进 boot.img
        又要写进 extlinux.conf 默认加载）。"""
        cfg_default = resolve_config(
            "orangepi-5-plus", "default", "debug", boards=boards)
        assert "rk3588-orangepi-5-plus-hx8399a-gt911.dtbo" \
            not in cfg_default["boot"]["board_overlays"]
        assert "rk3588-orangepi-5-plus-hx8399a-gt911.dtbo" \
            not in cfg_default["boot"]["default_overlays"]
        cfg_bringup = resolve_config(
            "orangepi-5-plus", "wks55fhd001wct-bringup", "debug", boards=boards)
        assert "rk3588-orangepi-5-plus-hx8399a-gt911.dtbo" \
            in cfg_bringup["boot"]["board_overlays"]
        assert "rk3588-orangepi-5-plus-hx8399a-gt911.dtbo" \
            in cfg_bringup["boot"]["default_overlays"]

    def test_board_overlay_dtso_source_exists(self):
        """对应 .dtso 源文件必须存在，否则 device-tree-overlay 编不出 dtbo。"""
        from pathlib import Path
        src = Path(
            "components/board/orangepi-5-plus/dtso/"
            "rk3588-orangepi-5-plus-hx8399a-gt911.dtso"
        )
        assert src.is_file(), f"缺失 dtso 源: {src}"

    def test_gt911_cfg_blob_in_board_firmware_tree(self):
        """GT911 cfg blob 落在板目录 firmware/touch/goodix_911_cfg.bin，与
        同目录的 .cfg 可读 hex 源同源；186 字节 = mainline GOODIX_CONFIG_911_
        LENGTH。部署走 rootfs.extra_firmware source='local'（仅 wks55fhd001wct
        -bringup product 启用，见下方 test_gt911_cfg_only_on_bringup_product）。
        """
        from pathlib import Path
        blob = Path(
            "components/board/orangepi-5-plus/firmware/touch/goodix_911_cfg.bin"
        )
        assert blob.is_file(), f"缺失 cfg blob: {blob}"
        assert blob.stat().st_size == 186, (
            f"GT911 cfg 必须 186 字节，实际 {blob.stat().st_size}")

    def test_gt911_cfg_only_on_bringup_product(self, boards):
        """goodix-911-cfg extra_firmware 条目仅在 wks55fhd001wct-bringup
        product 下出现；default 裸机镜像不携带该 blob。source='local' 直接
        从板目录 firmware/touch/ 拷到 rootfs /lib/firmware/。"""
        cfg_default = resolve_config(
            "orangepi-5-plus", "default", "debug", boards=boards)
        names = [e["name"] for e in cfg_default["rootfs"].get("extra_firmware", [])]
        assert "goodix-911-cfg" not in names, (
            f"default product 不该带触摸 blob；实际 extra_firmware={names}")
        cfg_bringup = resolve_config(
            "orangepi-5-plus", "wks55fhd001wct-bringup", "debug", boards=boards)
        bringup_fw = {e["name"]: e
                      for e in cfg_bringup["rootfs"].get("extra_firmware", [])}
        assert "goodix-911-cfg" in bringup_fw
        gt = bringup_fw["goodix-911-cfg"]
        assert gt["source"] == "local"
        assert gt["src_dir"] == "firmware/touch"
        assert gt["files"] == ["goodix_911_cfg.bin"]
        assert gt["dest"] == "lib/firmware"


class TestOrangePi5PlusHdmirxOverlay:
    """HDMI RX (HDMI IN) 启用 overlay 文件 + config 接入。

    BSP rk3588-orangepi-5-plus.dts:323-325 显式 status="disabled"；本 overlay
    仅翻 status="okay"。CONFIG_VIDEO_ROCKCHIP_HDMIRX=y 已 in-tree built-in。
    """

    @pytest.fixture()
    def merged(self, boards):
        return get_board_config("orangepi-5-plus", boards=boards)

    @pytest.fixture()
    def dtso_path(self):
        from pathlib import Path
        return Path(
            "components/board/orangepi-5-plus/dtso/"
            "rk3588-orangepi-5-plus-hdmirx-enable.dtso"
        )

    def test_dtso_source_exists(self, dtso_path):
        assert dtso_path.is_file(), f"缺失 dtso 源: {dtso_path}"

    def test_dtso_only_flips_status(self, dtso_path):
        """dtso 内容仅含一处 &hdmirx_ctrler reference + status="okay"。"""
        text = dtso_path.read_text()
        assert "&hdmirx_ctrler" in text
        assert 'status = "okay"' in text
        # 必须用 plugin overlay 模式（否则 dtc 不会把 &label{} 包成 fragment）
        assert "/dts-v1/;" in text
        assert "/plugin/;" in text

    def test_dtso_does_not_redeclare_dtsi_props(self, dtso_path):
        """dtso 不应重申板 dtsi 已写齐的属性（HPD/det-gpio/pinctrl），避免重复维护。"""
        text = dtso_path.read_text()
        # 检查非注释行（粗略 grep — dtso 注释用 // 与 /* ... */，不在 hot path 上）
        # 用简单子串扫描足够：这三个 token 在 dtsi 出现，overlay 翻 status 不该重申
        # 仅检查非注释正文中的出现：通过去掉块注释 + 行注释后判断
        import re
        # 去掉 /* ... */ 块注释
        stripped = re.sub(r"/\*[\s\S]*?\*/", "", text)
        # 去掉 // 行注释
        stripped = re.sub(r"//.*", "", stripped)
        for token in ("hpd-trigger-level", "hdmirx-det-gpios", "pinctrl-0", "pinctrl-names"):
            assert token not in stripped, (
                f"dtso 正文（去注释后）不应包含 {token!r}，由板 dtsi 维护")

    def test_board_overlays_includes_hdmirx(self, merged):
        overlays = merged["boot"]["board_overlays"]
        assert "rk3588-orangepi-5-plus-hdmirx-enable.dtbo" in overlays

    def test_default_overlays_includes_hdmirx(self, merged):
        default_overlays = merged["boot"]["default_overlays"]
        assert "rk3588-orangepi-5-plus-hdmirx-enable.dtbo" in default_overlays


class TestOrangePi5PlusRTL8852BEOOTChain:
    """RTL8852BE OOT 链路三块字段与 radxa-rock5b 等价（按值比较）。"""

    @pytest.fixture()
    def merged(self, boards):
        return get_board_config("orangepi-5-plus", boards=boards)

    @pytest.fixture()
    def rock5b(self, boards):
        return get_board_config("radxa-rock5b", boards=boards)

    def test_oot_sources_rkwifibt(self, merged):
        rkwifibt = merged["kernel"]["oot_sources"]["rkwifibt"]
        assert rkwifibt["repo"] == "https://github.com/radxa/rkwifibt.git"
        assert rkwifibt["branch"] == "develop"

    def test_oot_sources_equivalent_to_rock5b(self, merged, rock5b):
        assert merged["kernel"]["oot_sources"] == rock5b["kernel"]["oot_sources"]

    def test_oot_modules_has_rtl8852be(self, merged):
        # SoC 层无 oot_modules 基础列表，board 层 `+oot_modules` 保留 `+` 前缀。
        oot = merged["kernel"].get("oot_modules") or merged["kernel"].get("+oot_modules", [])
        labels = [m.get("label") for m in oot]
        assert any("rtl8852be" in (lbl or "") for lbl in labels), (
            f"oot_modules 应含 rtl8852be 条目；实际 labels: {labels}")

    def test_oot_modules_equivalent_to_rock5b(self, merged, rock5b):
        merged_oot = merged["kernel"].get("oot_modules") or merged["kernel"].get("+oot_modules", [])
        rock5b_oot = rock5b["kernel"].get("oot_modules") or rock5b["kernel"].get("+oot_modules", [])
        assert merged_oot == rock5b_oot

    def test_extra_firmware_has_rkwifibt(self, merged):
        extra = merged["rootfs"]["extra_firmware"]
        names = [e.get("name") for e in extra]
        assert "rkwifibt-rtl8852be" in names

    def test_extra_firmware_rkwifibt_entry_equivalent_to_rock5b(self, merged, rock5b):
        merged_rkwifibt = [e for e in merged["rootfs"]["extra_firmware"]
                           if e.get("name") == "rkwifibt-rtl8852be"]
        rock5b_rkwifibt = [e for e in rock5b["rootfs"]["extra_firmware"]
                           if e.get("name") == "rkwifibt-rtl8852be"]
        assert merged_rkwifibt == rock5b_rkwifibt



class TestOrangePi5PlusLunchTargets:
    """OrangePi 5 Plus lunch target 自动出现在可用目标列表。"""

    def test_targets_include_default_debug_and_release(self, boards):
        targets = set(get_valid_targets(boards=boards))
        assert "orangepi-5-plus-default-debug" in targets
        assert "orangepi-5-plus-default-release" in targets
