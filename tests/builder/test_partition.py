"""分区表转换测试。"""

from builder.partition import PartitionTable, Partition
from builder.partition.rockchip import RockchipPartitionConverter


class TestPartitionTable:
    def test_from_config(self):
        config = {
            "format": "gpt",
            "entries": [
                {"name": "boot", "offset": "0x8000", "size": "0x20000", "type": "ext4"},
                {"name": "rootfs", "offset": "0x40000", "size": "remaining", "type": "ext4"},
            ],
        }
        table = PartitionTable.from_config(config)
        assert table.format == "gpt"
        assert len(table.entries) == 2
        assert table.entries[0].name == "boot"
        assert table.entries[1].size == "remaining"

    def test_default_values(self):
        table = PartitionTable.from_config({})
        assert table.format == "gpt"
        assert table.sector_size == 512
        assert table.entries == []


class TestRockchipConverter:
    FULL_CONFIG = {
        "format": "gpt",
        "entries": [
            {"name": "idbloader", "offset": "0x40", "size": "0x2000", "type": "raw"},
            {"name": "uboot", "offset": "0x4000", "size": "0x2000", "type": "raw"},
            {"name": "boot", "offset": "0x8000", "size": "0x20000", "type": "ext4"},
            {"name": "rootfs", "offset": "0x40000", "size": "0x200000", "type": "ext4"},
            {"name": "userdata", "offset": "0x240000", "size": "remaining", "type": "ext4"},
        ],
    }

    def test_contains_header(self):
        converter = RockchipPartitionConverter()
        result = converter.convert(self.FULL_CONFIG)
        assert "FIRMWARE_VER:1.0" in result
        assert "TYPE: GPT" in result
        assert "MANUFACTURER:flange" in result

    def test_cmdline_format(self):
        converter = RockchipPartitionConverter()
        result = converter.convert(self.FULL_CONFIG)
        assert "CMDLINE:mtdparts=rk29xxnand:" in result

    def test_idbloader_excluded_from_mtdparts(self):
        converter = RockchipPartitionConverter()
        result = converter.convert(self.FULL_CONFIG)
        # 找到 CMDLINE 行
        cmdline = [l for l in result.split("\n") if l.startswith("CMDLINE:")][0]
        assert "idbloader" not in cmdline

    def test_remaining_uses_grow(self):
        converter = RockchipPartitionConverter()
        result = converter.convert(self.FULL_CONFIG)
        assert "(userdata:grow)" in result

    def test_regular_partitions_format(self):
        converter = RockchipPartitionConverter()
        result = converter.convert(self.FULL_CONFIG)
        cmdline = [l for l in result.split("\n") if l.startswith("CMDLINE:")][0]
        assert "0x2000@0x4000(uboot)" in cmdline
        assert "0x20000@0x8000(boot)" in cmdline
        assert "0x200000@0x40000(rootfs)" in cmdline
