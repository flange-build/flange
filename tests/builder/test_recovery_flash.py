"""recovery 在 image 组装与 flash-config 中的集成测试（§5.6 / §5.7）。"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from builder.flash import (
    AllwinnerA733FlashStrategy,
    FlashConfig,
    FlashConfigGenerator,
    RockchipFlashStrategy,
)
from builder.platforms.allwinnera733.image import AllwinnerA733ImageBuilder
from builder.platforms.rockchip.image import RockchipImageBuilder


# ── ImageBuilder 分区镜像映射含 recovery（§5.1 / §5.2） ─────────


class TestImagePartitionMap:
    def test_rockchip_image_includes_recovery(self):
        assert RockchipImageBuilder.PARTITION_IMAGES["recovery"] == "recovery/recovery.img"

    def test_a733_image_includes_recovery(self):
        assert AllwinnerA733ImageBuilder.PARTITION_IMAGES["recovery"] == "recovery/recovery.img"


# ── FlashStrategy.partition_image_map（§5.3 / §5.4） ──────────


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


# ── FlashConfigGenerator 写入 recovery + protected 元数据（§5.5 / §5.7） ──


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


# ── 整盘 image dd 顺序（§5.6） ─────────────────────────────────


class TestRawImageRecoveryEntry:
    """RockchipImageBuilder.compile 中的 dd 循环依赖 PARTITION_IMAGES + entries
    顺序逐分区写入。这里仅做静态断言：recovery 在 entries 中、PARTITION_IMAGES
    中能定位到 recovery/recovery.img；compile 中的"image_path 不存在则跳过"
    覆盖了 recovery 镜像未生成的边界场景。"""

    def test_rockchip_image_partition_order(self):
        """boot → recovery → rootfs，recovery 紧贴在 boot 之后、rootfs 之前。"""
        cfg = _rockchip_full_config(recovery_enabled=True)
        builder = RockchipImageBuilder(docker=None, source=None)
        entries = builder._resolve_entries(cfg["partitions"]["entries"])
        names = [e["name"] for e in entries]
        assert names.index("boot") < names.index("recovery")
        assert names.index("recovery") < names.index("rootfs")

    def test_rockchip_image_recovery_offset_size(self):
        cfg = _rockchip_full_config(recovery_enabled=True)
        builder = RockchipImageBuilder(docker=None, source=None)
        entries = builder._resolve_entries(cfg["partitions"]["entries"])
        recovery = next(e for e in entries if e["name"] == "recovery")
        # 紧随 boot：boot offset=0x8000 + size=0x20000 = recovery offset=0x28000
        assert recovery["_offset_sectors"] == 0x28000
        # 0x100000 sectors = 512MB
        assert recovery["_size_sectors"] * 512 == 512 * 1024 * 1024
