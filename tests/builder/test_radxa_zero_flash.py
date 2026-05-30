"""Radxa Zero flash-config 生成集成测试。

覆盖 amlogic-flash spec 中 "Radxa Zero eMMC fastboot 刷写" requirement：
- partition image map 不含 recovery（首版关闭）
- pre_flash.download_boot 指向裸 FIP u-boot.bin（pyamlboot 引导镜像）
- fastboot 写入命令含 bootloader/boot/rootfs，不含 recovery

用真实 resolve_config("radxa-zero", ...) 产出 FINAL_CONFIG，再走
FlashConfigGenerator.generate 落 flash-config.json，断言端到端形态。
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from builder.config.registry import resolve_config
from builder.flash import AmlogicFlashStrategy, FlashConfigGenerator


@pytest.fixture(scope="module")
def radxa_zero_config():
    return resolve_config("radxa-zero", "default", "debug")


class TestRadxaZeroPartitionMap:
    """partition_image_map 不含 recovery（recovery.enabled=False）。"""

    def test_map_excludes_recovery(self, radxa_zero_config):
        s = AmlogicFlashStrategy()
        m = s.partition_image_map(radxa_zero_config)
        assert m["bootloader"] == "bootloader/u-boot.bin.sd.bin"
        assert m["boot"] == "boot/boot.img"
        assert m["rootfs"] == "rootfs/rootfs.img"
        assert "recovery" not in m


class TestRadxaZeroPreFlash:
    """pre_flash 指向裸 FIP u-boot.bin（bootloader builder 实际产出名）。"""

    def test_download_boot_is_bare_fip(self, radxa_zero_config):
        s = AmlogicFlashStrategy()
        pf = s.generate_pre_flash_config(radxa_zero_config)
        # bootloader builder collect 产出 (bootloader, fip) → u-boot.bin
        assert pf.download_boot == "bootloader/u-boot.bin"
        assert not pf.download_boot.endswith(".sd.bin")
        assert pf.usb_vid == "1b8e"
        assert pf.usb_pid == "c003"


class TestRadxaZeroFlashConfigJson:
    """完整 flash-config.json 生成形态。"""

    def test_generated_flash_config(self, radxa_zero_config):
        gen = FlashConfigGenerator()
        with tempfile.TemporaryDirectory() as tmp:
            out = gen.generate(radxa_zero_config, Path(tmp))
            data = json.loads(out.read_text())

        assert data["platform"] == "amlogic"
        assert data["board"] == "radxa-zero"

        names = [p["name"] for p in data["partitions"]]
        # 顺序：bootloader (raw) + boot + rootfs，无 recovery
        assert names == ["bootloader", "boot", "rootfs"]
        assert "recovery" not in names

        # bootloader 为 raw → protected；boot/rootfs 非 protected
        by_name = {p["name"]: p for p in data["partitions"]}
        assert by_name["bootloader"]["type"] == "raw"
        assert by_name["bootloader"]["protected"] is True
        assert by_name["bootloader"]["image"] == "bootloader/u-boot.bin.sd.bin"
        assert by_name["boot"]["image"] == "boot/boot.img"
        assert by_name["rootfs"]["image"] == "rootfs/rootfs.img"

        # pre_flash 指向裸 FIP
        assert data["pre_flash"]["download_boot"] == "bootloader/u-boot.bin"

    def test_no_recovery_image_dependency(self, radxa_zero_config):
        """flash-config 不包含 recovery/recovery.img（spec scenario）。"""
        gen = FlashConfigGenerator()
        with tempfile.TemporaryDirectory() as tmp:
            out = gen.generate(radxa_zero_config, Path(tmp))
            text = out.read_text()
        assert "recovery/recovery.img" not in text
        assert "recovery" not in [
            p["name"] for p in json.loads(text)["partitions"]
        ]
