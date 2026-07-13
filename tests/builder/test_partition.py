"""分区表转换测试。"""

import pytest

from builder.config.registry import resolve_config
from builder.partition import PartitionTable, Partition
from builder.partition.rockchip import (
    RockchipPartitionConverter,
    parse_parameter_text,
    validate_parameter_capacity,
)


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


class TestRockchipParameterParser:
    """MTD/SPI NAND parameter 解析、顺序与容量门禁。"""

    TEXT = (
        "TYPE: MTD\n"
        "CMDLINE:mtdparts=rk29xxnand:"
        "0x1000@0x0(loader),0x2000@0x1000(uboot),"
        "0x2000@0x3000(amp),-@0x5000(rootfs:grow)\n"
    )

    def test_parse_named_mtd_entries_and_flags(self):
        entries = parse_parameter_text(self.TEXT)

        assert [entry.name for entry in entries] == [
            "loader", "uboot", "amp", "rootfs"]
        assert entries[2].offset == 0x3000
        assert entries[2].size == 0x2000
        assert entries[3].size is None
        assert entries[3].flags == ("grow",)

    def test_empty_device_prefix_is_supported(self):
        entries = parse_parameter_text(
            "CMDLINE:mtdparts=:0x1000@0x0(boot),-@0x1000(rootfs)\n")
        assert [entry.name for entry in entries] == ["boot", "rootfs"]

    def test_overlapping_partitions_are_rejected(self):
        text = (
            "CMDLINE:mtdparts=:0x2000@0x0(boot),"
            "0x1000@0x1000(amp)\n"
        )
        with pytest.raises(ValueError, match="重叠"):
            parse_parameter_text(text)

    def test_remaining_partition_must_be_last(self):
        text = (
            "CMDLINE:mtdparts=:-@0x0(rootfs),"
            "0x1000@0x1000(data)\n"
        )
        with pytest.raises(ValueError, match="必须位于最后"):
            parse_parameter_text(text)

    def test_capacity_rejects_partition_end_past_device(self):
        entries = parse_parameter_text(
            "CMDLINE:mtdparts=:0x2000@0xf0000(boot)\n")
        with pytest.raises(ValueError, match="超出存储容量"):
            validate_parameter_capacity(entries, 128 * 1024 * 1024)


# ── recovery 分区在真实平台配置中可解析 ──────────────────────────


class TestRecoveryPartitionLayout:
    """从 SoC 配置三层合并后，启用 recovery 的 target 必须能解出 recovery 分区。"""

    @pytest.mark.parametrize(
        "board,product,variant",
        [
            ("radxa-zero3w", "default", "release"),
            ("tspi-rk3566", "default", "release"),
            ("radxa-cubie-a7z", "default", "release"),
        ],
    )
    def test_recovery_partition_resolvable(self, board, product, variant):
        cfg = resolve_config(board, product, variant)
        # recovery 默认启用（platform 层默认 enabled=True）
        assert cfg.get("recovery", {}).get("enabled") is True
        table = PartitionTable.from_config(cfg["partitions"])
        recovery = [e for e in table.entries if e.name == "recovery"]
        assert len(recovery) == 1, f"{board} 应有恰好一个 recovery 分区"
        entry = recovery[0]
        assert entry.type == "ext4"
        assert entry.offset, "recovery 分区必须有 offset"
        assert entry.size, "recovery 分区必须有 size"
        # offset/size 必须是合法 hex/十进制字符串
        int(entry.offset, 0)
        int(entry.size, 0)

    def test_rk3566_recovery_size_512mb(self):
        """RK3566 默认 recovery 分区为 512MB（0x100000 sectors × 512 bytes）。"""
        cfg = resolve_config("radxa-zero3w", "default", "release")
        recovery = next(e for e in cfg["partitions"]["entries"] if e["name"] == "recovery")
        assert int(recovery["size"], 0) * 512 == 512 * 1024 * 1024

    def test_recovery_immediately_before_rootfs(self):
        """recovery 必须紧贴 rootfs 之前（boot → recovery → rootfs，无空洞）。

        layout 设计：维护工具固定按 GPT 顺序定位 recovery，rootfs 拉到末尾以
        最大化容量；不再有 userdata 分区。
        """
        cfg = resolve_config("radxa-zero3w", "default", "release")
        entries_list = cfg["partitions"]["entries"]
        entries = {e["name"]: e for e in entries_list}
        names = [e["name"] for e in entries_list]
        assert "userdata" not in entries
        # recovery 紧贴在 rootfs 之前
        assert names.index("recovery") + 1 == names.index("rootfs")
        # 无空洞：recovery_end == rootfs_offset
        recovery_end = int(entries["recovery"]["offset"], 0) + int(entries["recovery"]["size"], 0)
        assert int(entries["rootfs"]["offset"], 0) == recovery_end
        # rootfs 占满末尾
        assert entries["rootfs"]["size"] == "remaining"

    @pytest.mark.parametrize(
        "board,product,variant",
        [
            ("radxa-zero3w", "default", "release"),
            ("radxa-cubie-a7z", "default", "release"),
        ],
    )
    def test_rootfs_has_initial_image_size_and_auto_grow(self, board, product, variant):
        cfg = resolve_config(board, product, variant)
        rootfs = next(e for e in cfg["partitions"]["entries"] if e["name"] == "rootfs")
        assert rootfs["size"] == "remaining"
        assert rootfs["image_size"] == "2G"
        assert rootfs["grow_on_first_boot"] is True
