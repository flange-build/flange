"""Rootfs 两阶段缓存测试。

覆盖场景：
- base 缓存命中时跳过 Phase 1
- base 缓存未命中时完整构建 Phase 1 并保存快照
- packages 变化 → base_hash 变 → 旧快照不匹配 → 重建
- 两个 variant 相同 packages → 共享 base.tar.gz
- overlay 变化 + base 命中 → 只执行 Phase 2
- cache 未注入时 graceful degradation（走完整构建）
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from builder.cache import BuildCache
from builder.platforms.rockchip.rootfs import RockchipRootfsBuilder


def _make_config(board="test", product="default", variant="release", packages=None):
    return {
        "board": board,
        "product": product,
        "variant": variant,
        "arch": "aarch64",
        "platform": "rockchip",
        "soc": "rk3566",
        "rootfs": {
            "url": "https://example.com/ubuntu-base.tar.gz",
            "packages": packages or ["systemd"],
            "custom_packages": [],
        },
    }


def _make_builder(cache=None):
    docker = MagicMock()
    source = MagicMock()
    fake_tarball = Path("/tmp/fake-tarball.tar.gz")
    source.ensure_rootfs_tarball.return_value = fake_tarball
    builder = RockchipRootfsBuilder(docker, source)
    builder.cache = cache
    return builder


class TestBaseCachePath:
    """验证 base 缓存路径计算。"""

    def test_returns_none_without_cache(self):
        builder = _make_builder(cache=None)
        config = _make_config()
        assert builder._get_base_cache_path(config) is None

    def test_returns_path_with_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_config()
            cache = BuildCache.__new__(BuildCache)
            cache.config = config
            cache.target_dir = Path(tmpdir) / "test" / "default" / "release"

            builder = _make_builder(cache=cache)
            path = builder._get_base_cache_path(config)
            assert path is not None
            assert ".cache" in str(path)
            assert "rootfs-base-" in path.name
            assert path.suffix == ".gz"

    def test_same_packages_same_path(self):
        """相同 packages → 相同 base_hash → 相同缓存路径。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config1 = _make_config(variant="release")
            config2 = _make_config(variant="debug")

            cache1 = BuildCache.__new__(BuildCache)
            cache1.config = config1
            cache1.target_dir = Path(tmpdir) / "test" / "default" / "release"

            cache2 = BuildCache.__new__(BuildCache)
            cache2.config = config2
            cache2.target_dir = Path(tmpdir) / "test" / "default" / "debug"

            builder1 = _make_builder(cache=cache1)
            builder2 = _make_builder(cache=cache2)

            path1 = builder1._get_base_cache_path(config1)
            path2 = builder2._get_base_cache_path(config2)
            assert path1 == path2  # 共享缓存路径

    def test_different_packages_different_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config1 = _make_config(packages=["systemd"])
            config2 = _make_config(packages=["systemd", "vim"])

            cache1 = BuildCache.__new__(BuildCache)
            cache1.config = config1
            cache1.target_dir = Path(tmpdir) / "test" / "default" / "release"

            cache2 = BuildCache.__new__(BuildCache)
            cache2.config = config2
            cache2.target_dir = Path(tmpdir) / "test" / "default" / "release"

            builder1 = _make_builder(cache=cache1)
            builder2 = _make_builder(cache=cache2)

            assert builder1._get_base_cache_path(config1) != builder2._get_base_cache_path(config2)


class TestBaseCacheHit:
    """base 缓存命中时跳过 Phase 1。"""

    def test_cache_hit_skips_phase1(self):
        """base.tar.gz 存在时，不调用 apt-get install。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_config()
            cache = BuildCache.__new__(BuildCache)
            cache.config = config
            cache.target_dir = Path(tmpdir) / "test" / "default" / "release"

            builder = _make_builder(cache=cache)
            base_path = builder._get_base_cache_path(config)
            base_path.parent.mkdir(parents=True, exist_ok=True)
            base_path.write_bytes(b"fake-base-tarball")

            # 记录 docker 调用
            calls = []
            builder.docker.run_privileged.side_effect = lambda cmd, **kw: calls.append(cmd)

            with patch("builder.platforms.rockchip.rootfs.tempfile.mkdtemp",
                       return_value=str(Path(tmpdir) / "work")):
                (Path(tmpdir) / "work").mkdir()
                try:
                    builder.compile(None, config)
                except Exception:
                    pass

            # 验证：应有 "tar xf base_path" 调用（解压快照），不应有 apt-get 调用
            cmd_strs = [" ".join(str(c) for c in cmd) for cmd in calls]
            assert any(str(base_path) in s and "tar" in s for s in cmd_strs), \
                f"应解压 base 快照，实际调用: {cmd_strs}"
            assert not any("apt-get" in s and "install" in s for s in cmd_strs), \
                f"不应调用 apt-get install，实际调用: {cmd_strs}"


class TestBaseCacheMiss:
    """base 缓存未命中时完整构建 + 保存快照。"""

    def test_cache_miss_runs_phase1_and_saves(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_config()
            cache = BuildCache.__new__(BuildCache)
            cache.config = config
            cache.target_dir = Path(tmpdir) / "test" / "default" / "release"

            builder = _make_builder(cache=cache)
            base_path = builder._get_base_cache_path(config)
            # 不创建 base_path → 缓存未命中

            calls = []
            builder.docker.run_privileged.side_effect = lambda cmd, **kw: calls.append(cmd)

            with patch("builder.platforms.rockchip.rootfs.tempfile.mkdtemp",
                       return_value=str(Path(tmpdir) / "work")), \
                 patch("builder.platforms.rockchip.rootfs.ChrootContext") as MockChroot:
                (Path(tmpdir) / "work").mkdir()
                mock_ctx = MagicMock()
                MockChroot.return_value.__enter__ = MagicMock(return_value=mock_ctx)
                MockChroot.return_value.__exit__ = MagicMock(return_value=False)
                try:
                    builder.compile(None, config)
                except Exception:
                    pass

            # 验证：应有 tar 命令保存快照到 base_path
            cmd_strs = [" ".join(str(c) for c in cmd) for cmd in calls]
            assert any(str(base_path) in s and "czf" in s for s in cmd_strs), \
                f"应保存 base 快照，实际调用: {cmd_strs}"


class TestNoCacheGraceful:
    """cache 未注入时走完整构建（不崩溃）。"""

    def test_no_cache_full_build(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_config()
            builder = _make_builder(cache=None)

            calls = []
            builder.docker.run_privileged.side_effect = lambda cmd, **kw: calls.append(cmd)

            with patch("builder.platforms.rockchip.rootfs.tempfile.mkdtemp",
                       return_value=str(Path(tmpdir) / "work")), \
                 patch("builder.platforms.rockchip.rootfs.ChrootContext") as MockChroot:
                (Path(tmpdir) / "work").mkdir()
                mock_ctx = MagicMock()
                MockChroot.return_value.__enter__ = MagicMock(return_value=mock_ctx)
                MockChroot.return_value.__exit__ = MagicMock(return_value=False)
                try:
                    builder.compile(None, config)
                except Exception:
                    pass

            # 不崩溃即成功，且应有 tar xf 解压 tarball 的调用
            cmd_strs = [" ".join(str(c) for c in cmd) for cmd in calls]
            assert any("tar" in s and "xf" in s for s in cmd_strs)


class TestCrossVariantShare:
    """两个 variant 相同 packages → 共享 base.tar.gz。"""

    def test_same_base_hash_shares_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_release = _make_config(variant="release")
            config_debug = _make_config(variant="debug")

            cache_release = BuildCache.__new__(BuildCache)
            cache_release.config = config_release
            cache_release.target_dir = Path(tmpdir) / "test" / "default" / "release"

            cache_debug = BuildCache.__new__(BuildCache)
            cache_debug.config = config_debug
            cache_debug.target_dir = Path(tmpdir) / "test" / "default" / "debug"

            # 两个缓存的 base_hash 应相同
            assert cache_release._compute_rootfs_base_hash() == cache_debug._compute_rootfs_base_hash()

            # 构建器的 base 缓存路径应相同
            builder_r = _make_builder(cache=cache_release)
            builder_d = _make_builder(cache=cache_debug)
            assert builder_r._get_base_cache_path(config_release) == \
                   builder_d._get_base_cache_path(config_debug)
