"""rootfs/image 初始镜像大小测试。"""

from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import MagicMock

import pytest

from builder.docker import BuildError
from builder.platforms.allwinnera733.image import AllwinnerA733ImageBuilder
from builder.platforms.allwinnera733.rootfs import AllwinnerA733RootfsBuilder
from builder.platforms.rockchip.image import RockchipImageBuilder
from builder.platforms.rockchip.rootfs import RockchipRootfsBuilder


def _cfg(rootfs_entry: dict) -> dict:
    return {
        "partitions": {
            "format": "gpt",
            "sector_size": 512,
            "entries": [
                {"name": "boot", "offset": "0x8000", "size": "0x20000", "type": "ext4"},
                {"name": "rootfs", "offset": "0x40000", "type": "ext4", **rootfs_entry},
            ],
        },
    }


class TestRootfsBuilderImageSize:
    @pytest.mark.parametrize(
        "builder_cls",
        [RockchipRootfsBuilder, AllwinnerA733RootfsBuilder],
    )
    def test_remaining_rootfs_uses_image_size(self, builder_cls):
        builder = builder_cls(docker=MagicMock(), source=MagicMock())
        cfg = _cfg({"size": "remaining", "image_size": "2G"})
        assert builder._partition_size_mb(cfg, "rootfs") == 2048

    @pytest.mark.parametrize(
        "builder_cls",
        [RockchipRootfsBuilder, AllwinnerA733RootfsBuilder],
    )
    def test_remaining_without_image_size_keeps_compat_default(self, builder_cls):
        builder = builder_cls(docker=MagicMock(), source=MagicMock())
        cfg = _cfg({"size": "remaining"})
        assert builder._partition_size_mb(cfg, "rootfs") == 4096

    @pytest.mark.parametrize(
        "builder_cls",
        [RockchipRootfsBuilder, AllwinnerA733RootfsBuilder],
    )
    def test_fixed_size_without_image_size_uses_partition_size(self, builder_cls):
        builder = builder_cls(docker=MagicMock(), source=MagicMock())
        cfg = _cfg({"size": "0x100000"})
        assert builder._partition_size_mb(cfg, "rootfs") == 512

    def test_rootfs_content_larger_than_image_size_raises(self):
        docker = MagicMock()
        docker.run.return_value = CompletedProcess(
            args=["du"], returncode=0, stdout="1950\t/rootfs\n")
        builder = RockchipRootfsBuilder(docker=docker, source=MagicMock())
        with pytest.raises(BuildError, match="image_size"):
            builder._ensure_rootfs_fits_image(Path("/rootfs"), image_size_mb=2048)


class TestImageBuilderInitialPartitionSize:
    @pytest.mark.parametrize(
        "builder_cls",
        [RockchipImageBuilder, AllwinnerA733ImageBuilder],
    )
    def test_remaining_rootfs_uses_image_size_for_gpt_entry(self, builder_cls):
        builder = builder_cls(docker=MagicMock(), source=MagicMock())
        entries = builder._resolve_entries(
            _cfg({"size": "remaining", "image_size": "2G"})["partitions"]["entries"])
        rootfs = next(e for e in entries if e["name"] == "rootfs")
        assert rootfs["_size_sectors"] == (2 * 1024 * 1024 * 1024) // 512

    @pytest.mark.parametrize(
        "builder_cls",
        [RockchipImageBuilder, AllwinnerA733ImageBuilder],
    )
    def test_remaining_without_image_size_keeps_compat_default(self, builder_cls):
        builder = builder_cls(docker=MagicMock(), source=MagicMock())
        entries = builder._resolve_entries(
            _cfg({"size": "remaining"})["partitions"]["entries"])
        rootfs = next(e for e in entries if e["name"] == "rootfs")
        assert rootfs["_size_sectors"] == (4 * 1024 * 1024 * 1024) // 512
