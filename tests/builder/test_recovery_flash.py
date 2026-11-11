"""recovery 在 image 组装与 flash-config 中的集成测试。"""

from __future__ import annotations

import tempfile
from pathlib import Path

from builder.flash import (
    AllwinnerA733FlashStrategy,
    FlashConfig,
    FlashConfigGenerator,
    RockchipFlashStrategy,
)


# ── FlashStrategy.partition_image_map ──────────


def _rockchip_full_config(*, recovery_enabled: bool) -> dict:
    return {
        "platform": "rockchip",
        "flash_tool": "upgrade_tool",
        "board": "radxa-zero3w",
        "product": "default",
        "variant": "release",
        "recovery": {
            "enabled": recovery_enabled,
            "transport": "adb",
            "protected_partitions": ["recovery"],
        },
        "partitions": {
            "format": "gpt", "sector_size": 512,
            "entries": [
                {"name": "idbloader", "offset": "0x40",     "size": "0x2000",   "type": "raw"},
                {"name": "uboot",     "offset": "0x4000",   "size": "0x2000",   "type": "raw"},
                {"name": "boot",      "offset": "0x8000",   "size": "0x20000",  "type": "ext4"},
                {"name": "recovery",  "offset": "0x28000",  "size": "0x100000", "type": "ext4"},
                {"name": "rootfs",    "offset": "0x128000", "size": "remaining", "type": "ext4"},
            ],
        },
    }


def _a733_full_config(*, recovery_enabled: bool) -> dict:
    return {
        "platform": "allwinnera733",
        "flash_tool": "dd",
        "board": "radxa-cubie-a7z",
        "product": "default",
        "variant": "release",
        "recovery": {
            "enabled": recovery_enabled,
            "transport": "adb",
            "protected_partitions": ["recovery"],
        },
        "partitions": {
            "format": "gpt", "sector_size": 512,
            "entries": [
                {"name": "boot0",        "offset": "0x100",    "size": "0x700",    "type": "raw"},
                {"name": "boot0_ufs",    "offset": "0x810",    "size": "0x700",    "type": "raw"},
                {"name": "boot_package", "offset": "0x6000",   "size": "0x2000",   "type": "raw"},
                {"name": "boot",         "offset": "0x8000",   "size": "0x20000",  "type": "ext4"},
                {"name": "recovery",     "offset": "0x28000",  "size": "0x100000", "type": "ext4"},
                {"name": "rootfs",       "offset": "0x128000", "size": "remaining", "type": "ext4"},
            ],
        },
    }


class TestRockchipFlashStrategyRecovery:
    def test_partition_image_map_includes_recovery_when_enabled(self):
        s = RockchipFlashStrategy()
        m = s.partition_image_map(_rockchip_full_config(recovery_enabled=True))
        assert m["recovery"] == "recovery/recovery.img"

    def test_partition_image_map_excludes_recovery_when_disabled(self):
        s = RockchipFlashStrategy()
        m = s.partition_image_map(_rockchip_full_config(recovery_enabled=False))
        assert "recovery" not in m


class TestA733FlashStrategyRecovery:
    def test_partition_image_map_includes_recovery_when_enabled(self):
        s = AllwinnerA733FlashStrategy()
        m = s.partition_image_map(_a733_full_config(recovery_enabled=True))
        assert m["recovery"] == "recovery/recovery.img"

    def test_partition_image_map_excludes_recovery_when_disabled(self):
        s = AllwinnerA733FlashStrategy()
        m = s.partition_image_map(_a733_full_config(recovery_enabled=False))
        assert "recovery" not in m


# ── FlashConfigGenerator 写入 recovery + protected 元数据 ──


class TestFlashConfigRecovery:
    def test_recovery_partition_present_with_image(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            FlashConfigGenerator().generate(
                _rockchip_full_config(recovery_enabled=True), Path(tmpdir))
            config = FlashConfig.from_json(Path(tmpdir) / "flash-config.json")
            recovery = next((p for p in config.partitions if p.name == "recovery"), None)
            assert recovery is not None
            assert recovery.image == "recovery/recovery.img"
            assert recovery.offset == "0x28000"
            assert recovery.type == "ext4"

    def test_recovery_partition_marked_protected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            FlashConfigGenerator().generate(
                _rockchip_full_config(recovery_enabled=True), Path(tmpdir))
            config = FlashConfig.from_json(Path(tmpdir) / "flash-config.json")
            recovery = next(p for p in config.partitions if p.name == "recovery")
            assert recovery.protected is True

    def test_raw_partitions_marked_protected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            FlashConfigGenerator().generate(
                _rockchip_full_config(recovery_enabled=True), Path(tmpdir))
            config = FlashConfig.from_json(Path(tmpdir) / "flash-config.json")
            idb = next(p for p in config.partitions if p.name == "idbloader")
            uboot = next(p for p in config.partitions if p.name == "uboot")
            assert idb.protected is True
            assert uboot.protected is True

    def test_rootfs_default_unprotected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            FlashConfigGenerator().generate(
                _rockchip_full_config(recovery_enabled=True), Path(tmpdir))
            config = FlashConfig.from_json(Path(tmpdir) / "flash-config.json")
            rootfs = next(p for p in config.partitions if p.name == "rootfs")
            assert rootfs.protected is False

    def test_recovery_absent_when_disabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            FlashConfigGenerator().generate(
                _rockchip_full_config(recovery_enabled=False), Path(tmpdir))
            config = FlashConfig.from_json(Path(tmpdir) / "flash-config.json")
            assert all(p.name != "recovery" for p in config.partitions)
