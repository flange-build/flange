"""分区大小解析工具测试。"""

import pytest

from builder.partition.size import (
    DEFAULT_REMAINING_BYTES,
    parse_size,
    resolve_image_size,
)


class TestParseSize:
    def test_parse_mebibytes(self):
        size = parse_size("1536M")
        assert size.bytes == 1536 * 1024 * 1024
        assert size.sectors == (1536 * 1024 * 1024) // 512
        assert size.mb == 1536

    def test_parse_gibibytes(self):
        size = parse_size("2G")
        assert size.bytes == 2 * 1024 * 1024 * 1024
        assert size.sectors == (2 * 1024 * 1024 * 1024) // 512
        assert size.mb == 2048

    def test_parse_hex_sectors(self):
        size = parse_size("0x400000")
        assert size.bytes == 0x400000 * 512
        assert size.sectors == 0x400000
        assert size.mb == 2048

    def test_invalid_unit_raises(self):
        with pytest.raises(ValueError, match="不支持的大小单位"):
            parse_size("2T")

    def test_unaligned_bytes_raises(self):
        with pytest.raises(ValueError, match="512B 对齐"):
            parse_size("513B")


class TestResolveImageSize:
    def test_image_size_overrides_remaining_size(self):
        entry = {"name": "rootfs", "size": "remaining", "image_size": "2G"}
        size = resolve_image_size(entry)
        assert size.bytes == 2 * 1024 * 1024 * 1024

    def test_remaining_without_image_size_uses_compat_default(self):
        entry = {"name": "rootfs", "size": "remaining"}
        size = resolve_image_size(entry)
        assert size.bytes == DEFAULT_REMAINING_BYTES

    def test_fixed_size_without_image_size_uses_partition_size(self):
        entry = {"name": "boot", "size": "0x20000"}
        size = resolve_image_size(entry)
        assert size.bytes == 0x20000 * 512
