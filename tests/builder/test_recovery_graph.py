"""recovery 组件在构建图与缓存中的位置测试。

覆盖 OpenSpec change add-recovery-boot 的任务 2.5 与 2.6：
- image 构建顺序包含 recovery 且位于 image 之前
- recovery 哈希响应 kernel / app / recovery 自身配置变化
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from builder.cache import BuildCache, DEPENDENCY_GRAPH, REQUIRED_ARTIFACTS
from builder.engine import _topo_sort


# ── 依赖图与拓扑排序 ────────────────────────────────────────────────


class TestRecoveryDependencyGraph:
    def test_recovery_in_graph(self):
        assert "recovery" in DEPENDENCY_GRAPH

    def test_recovery_depends_on_app_and_kernel(self):
        assert set(DEPENDENCY_GRAPH["recovery"]) == {"app", "kernel"}

    def test_image_depends_on_recovery(self):
        assert "recovery" in DEPENDENCY_GRAPH["image"]

    def test_topo_sort_image_includes_recovery_before_image(self):
        order = _topo_sort(DEPENDENCY_GRAPH, "image")
        assert "recovery" in order
        assert order.index("recovery") < order.index("image")

    def test_topo_sort_image_orders_recovery_after_kernel_and_app(self):
        order = _topo_sort(DEPENDENCY_GRAPH, "image")
        assert order.index("kernel") < order.index("recovery")
        assert order.index("app") < order.index("recovery")

    def test_topo_sort_recovery_does_not_pull_image(self):
        order = _topo_sort(DEPENDENCY_GRAPH, "recovery")
        assert "image" not in order
        assert "recovery" in order
        assert "kernel" in order
        assert "app" in order

    def test_required_artifacts_recovery(self):
        assert REQUIRED_ARTIFACTS.get("recovery") == ["recovery.img"]


# ── recovery 内容哈希 ──────────────────────────────────────────────


def _make_cache(tmpdir: Path, **config_overrides) -> BuildCache:
    config = {
        "board": "test-board",
        "product": "default",
        "variant": "release",
        "platform": "rockchip",
        "soc": "rk3566",
        "arch": "aarch64",
        "rootfs": {
            "url": "https://example.com/ubuntu-base.tar.gz",
            "packages": ["systemd"],
            "custom_packages": [],
        },
        "recovery": {
            "enabled": True,
            "packages": ["systemd", "udev"],
            "custom_packages": ["adbd", "recoveryctl"],
            "transport": "adb",
            "protected_partitions": ["recovery"],
        },
        "partitions": {
            "format": "gpt",
            "entries": [
                {"name": "boot", "offset": "0x8000", "size": "0x20000", "type": "ext4"},
                {"name": "rootfs", "offset": "0x40000", "size": "0x200000", "type": "ext4"},
                {"name": "recovery", "offset": "0x240000", "size": "0x100000", "type": "ext4"},
            ],
        },
    }
    config.update(config_overrides)
    cache = BuildCache.__new__(BuildCache)
    cache.config = config
    cache.target_dir = tmpdir / "test-board" / "default" / "release"
    cache._hash_cache = {}
    return cache


class TestRecoveryHash:
    def test_recovery_hash_stable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache1 = _make_cache(Path(tmpdir))
            cache2 = _make_cache(Path(tmpdir))
            assert cache1.compute_hash("recovery") == cache2.compute_hash("recovery")

    def test_recovery_hash_changes_on_recovery_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache1 = _make_cache(Path(tmpdir))
            h1 = cache1.compute_hash("recovery")

            cache2 = _make_cache(Path(tmpdir))
            cache2.config["recovery"]["packages"].append("strace")
            h2 = cache2.compute_hash("recovery")
            assert h1 != h2

    def test_recovery_hash_changes_on_partition_size(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache1 = _make_cache(Path(tmpdir))
            h1 = cache1.compute_hash("recovery")

            cache2 = _make_cache(Path(tmpdir))
            for entry in cache2.config["partitions"]["entries"]:
                if entry["name"] == "recovery":
                    entry["size"] = "0x80000"
            h2 = cache2.compute_hash("recovery")
            assert h1 != h2

    def test_recovery_hash_propagates_kernel_change(self):
        """kernel 上游哈希变化必须级联到 recovery（Merkle 链）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache1 = _make_cache(Path(tmpdir), kernel={"defconfig": "a"})
            h1 = cache1.compute_hash("recovery")

            cache2 = _make_cache(Path(tmpdir), kernel={"defconfig": "b"})
            h2 = cache2.compute_hash("recovery")
            assert h1 != h2

    def test_recovery_hash_propagates_app_change(self):
        """app 组件哈希变化必须级联到 recovery。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # app 组件的哈希基于 custom_packages 列表 + 各 App 目录树。
            # 这里只改 custom_packages 名（可不存在），观察 recovery 是否级联。
            cache1 = _make_cache(Path(tmpdir))
            cache1.config["rootfs"]["custom_packages"] = ["adbd"]
            h1 = cache1.compute_hash("recovery")

            cache2 = _make_cache(Path(tmpdir))
            cache2.config["rootfs"]["custom_packages"] = ["adbd", "recoveryctl"]
            h2 = cache2.compute_hash("recovery")
            assert h1 != h2

    def test_recovery_hash_distinct_from_rootfs(self):
        """recovery 与 rootfs 必须有不同的哈希命名空间。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = _make_cache(Path(tmpdir))
            assert cache.compute_hash("recovery") != cache.compute_hash("rootfs")
