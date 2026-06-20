"""Rockchip 镜像组装扇区参数化测试。

覆盖 rockchip-platform spec "Rockchip 镜像组装按 sector_size 支持 4096 字节
UFS 扇区" requirement —— 默认 512 行为不变；4096 时 offset/size 按目标扇区重算。
"""

from __future__ import annotations

import pytest

from builder.platforms.rockchip.image import RockchipImageBuilder

# RK3576 SoC 层 512B eMMC 布局的代表性 entries（offset/size 以 512B 扇区计）。
ENTRIES = [
    {"name": "idbloader", "offset": "0x40", "size": "0x2000", "type": "raw"},
    {"name": "uboot", "offset": "0x4000", "size": "0x2000", "type": "raw"},
    {"name": "boot", "offset": "0x8000", "size": "0x20000", "type": "ext4"},
    {"name": "rootfs", "offset": "0x128000", "size": "0x100000", "type": "ext4"},
]


@pytest.fixture()
def builder():
    # _resolve_sector / _resolve_entries 是纯逻辑，不触发 docker。
    return RockchipImageBuilder(None, None)


class TestSectorResolution:
    def test_defaults_to_512(self, builder):
        assert builder._resolve_sector({}) == 512
        assert builder._resolve_sector({"partitions": {}}) == 512

    def test_reads_sector_size_from_config(self, builder):
        cfg = {"partitions": {"sector_size": 4096}}
        assert builder._resolve_sector(cfg) == 4096


class TestResolveEntries512:
    """512 字节默认路径：offset/size 与原行为一致。"""

    def test_offsets_unchanged(self, builder):
        builder._sector = 512
        resolved = builder._resolve_entries(ENTRIES)
        by_name = {e["name"]: e for e in resolved}
        assert by_name["idbloader"]["_offset_sectors"] == 0x40
        assert by_name["uboot"]["_offset_sectors"] == 0x4000
        assert by_name["boot"]["_offset_sectors"] == 0x8000
        assert by_name["idbloader"]["_size_sectors"] == 0x2000


class TestResolveEntries4096:
    """4096 字节 UFS 路径：offset/size 按 off_512 × 512 ÷ 4096 重算。"""

    def test_offsets_recomputed(self, builder):
        builder._sector = 4096
        resolved = builder._resolve_entries(ENTRIES)
        by_name = {e["name"]: e for e in resolved}
        # 0x40 sector × 512 = 32768 B ÷ 4096 = 8
        assert by_name["idbloader"]["_offset_sectors"] == 8
        # 0x4000 sector × 512 = 8 MiB ÷ 4096 = 0x800
        assert by_name["uboot"]["_offset_sectors"] == 0x800
        # 0x8000 sector × 512 = 16 MiB ÷ 4096 = 0x1000
        assert by_name["boot"]["_offset_sectors"] == 0x1000

    def test_sizes_recomputed(self, builder):
        builder._sector = 4096
        resolved = builder._resolve_entries(ENTRIES)
        by_name = {e["name"]: e for e in resolved}
        # 0x2000 sector × 512 = 4 MiB ÷ 4096 = 0x400
        assert by_name["idbloader"]["_size_sectors"] == 0x400
        # 0x20000 sector × 512 = 64 MiB ÷ 4096 = 0x4000
        assert by_name["boot"]["_size_sectors"] == 0x4000
