"""构建引擎集成测试 — 依赖图拓扑排序与 App 组件集成。

覆盖场景：
- DEPENDENCY_GRAPH 包含 app 节点，rootfs 依赖 app
- 构建 image 时，app 出现在 rootfs 之前
- 构建 rootfs 时，app 出现在 rootfs 之前
- 单独构建 app 时，只包含 app 本身
- BuildEngine.build() 对 app 组件正确使用 AppBuilder（AppBuilder.build_all 被调用）
- App 组件 cache 哈希随 app.yaml 变化而改变
- App 组件 cache 哈希随 custom_packages 列表变化而改变
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from builder.engine import DEPENDENCY_GRAPH, BuildEngine, _topo_sort
from builder.cache import BuildCache


# ---------------------------------------------------------------------------
# 拓扑排序测试
# ---------------------------------------------------------------------------

class TestDependencyGraph:
    """验证 DEPENDENCY_GRAPH 结构与拓扑排序结果。"""

    def test_app节点存在于依赖图(self):
        """DEPENDENCY_GRAPH 必须包含 app 节点。"""
        assert "app" in DEPENDENCY_GRAPH

    def test_app无依赖(self):
        """app 节点自身不依赖其他组件。"""
        assert DEPENDENCY_GRAPH["app"] == []

    def test_rootfs依赖app(self):
        """rootfs 必须依赖 app（确保 .deb 先于 rootfs 构建）。"""
        assert "app" in DEPENDENCY_GRAPH["rootfs"]

    def test_构建image时app在rootfs之前(self):
        """topo_sort(image) 中 app 的索引必须小于 rootfs 的索引。"""
        order = _topo_sort(DEPENDENCY_GRAPH, "image")
        assert "app" in order
        assert "rootfs" in order
        assert order.index("app") < order.index("rootfs")

    def test_构建image时包含所有必要组件(self):
        """构建 image 时，依赖链应包含 app、rootfs、boot、bootloader、kernel。"""
        order = _topo_sort(DEPENDENCY_GRAPH, "image")
        for component in ("app", "rootfs", "boot", "kernel", "bootloader", "image"):
            assert component in order, f"{component} 应出现在 image 构建顺序中"

    def test_构建rootfs时app在rootfs之前(self):
        """topo_sort(rootfs) 中 app 必须先于 rootfs。"""
        order = _topo_sort(DEPENDENCY_GRAPH, "rootfs")
        assert "app" in order
        assert order.index("app") < order.index("rootfs")

    def test_构建rootfs时不含无关组件(self):
        """构建 rootfs 时，不应包含 kernel、bootloader、boot、image 等无关组件。"""
        order = _topo_sort(DEPENDENCY_GRAPH, "rootfs")
        for irrelevant in ("kernel", "bootloader", "boot", "image"):
            assert irrelevant not in order, f"{irrelevant} 不应出现在 rootfs 构建路径中"

    def test_单独构建app只含app本身(self):
        """topo_sort(app) 结果只包含 app 节点。"""
        order = _topo_sort(DEPENDENCY_GRAPH, "app")
        assert order == ["app"]

    def test_构建kernel不含app(self):
        """构建 kernel 时不需要 app 组件。"""
        order = _topo_sort(DEPENDENCY_GRAPH, "kernel")
        assert "app" not in order


# ---------------------------------------------------------------------------
# BuildEngine.build() app 分支测试
# ---------------------------------------------------------------------------

class TestBuildEngineApp:
    """验证 BuildEngine 对 app 组件使用 AppBuilder。"""

    def _make_config(self) -> dict:
        return {
            "board":    "test-board",
            "product":  "default",
            "variant":  "release",
            "arch":     "aarch64",
            "platform": "rockchip",
            "soc":      "rk3566",
            "rootfs":   {"custom_packages": []},
        }

    def test_build_app组件调用AppBuilder_build_all(self, tmp_path):
        """engine.build('app') 应创建 AppBuilder 并调用 build_all()。"""
        config = self._make_config()

        with (
            patch("builder.engine.DockerRunner"),
            patch("builder.engine.SourceManager"),
            patch("builder.engine.BuildCache") as MockCache,
            patch("builder.engine.AppBuilder") as MockAppBuilder,
        ):
            # 缓存始终认为需要重建
            mock_cache_instance = MockCache.return_value
            mock_cache_instance.is_up_to_date.return_value = False
            mock_cache_instance.compute_hash.return_value = "abc123"

            # AppBuilder.build_all 返回空字典
            mock_app_builder_instance = MockAppBuilder.return_value
            mock_app_builder_instance.build_all.return_value = {}

            engine = BuildEngine(config, project_dir=tmp_path)
            engine.build("app")

            # 断言 AppBuilder 被实例化
            assert MockAppBuilder.called, "AppBuilder 应被实例化"
            # 断言 build_all 被调用
            mock_app_builder_instance.build_all.assert_called_once()

    def test_build_app结果存入outputs(self, tmp_path):
        """build_all 的返回值应存入 engine._outputs['app']。"""
        config = self._make_config()
        fake_deb = tmp_path / "hello_1.0.0_aarch64.deb"
        fake_deb.touch()

        with (
            patch("builder.engine.DockerRunner"),
            patch("builder.engine.SourceManager"),
            patch("builder.engine.BuildCache") as MockCache,
            patch("builder.engine.AppBuilder") as MockAppBuilder,
        ):
            mock_cache_instance = MockCache.return_value
            mock_cache_instance.is_up_to_date.return_value = False
            mock_cache_instance.compute_hash.return_value = "abc123"

            mock_app_builder_instance = MockAppBuilder.return_value
            mock_app_builder_instance.build_all.return_value = {"hello": fake_deb}

            engine = BuildEngine(config, project_dir=tmp_path)
            engine.build("app")

            assert engine._outputs.get("app") == {"hello": fake_deb}

    def test_build_rootfs时不会直接构建app(self, tmp_path):
        """构建 rootfs 时，app 组件也经由依赖图触发，AppBuilder 应被调用。"""
        config = self._make_config()

        call_log: list[str] = []

        with (
            patch("builder.engine.DockerRunner"),
            patch("builder.engine.SourceManager"),
            patch("builder.engine.BuildCache") as MockCache,
            patch("builder.engine.AppBuilder") as MockAppBuilder,
            patch("builder.engine.importlib") as mock_importlib,
        ):
            mock_cache_instance = MockCache.return_value
            mock_cache_instance.is_up_to_date.return_value = False
            mock_cache_instance.compute_hash.return_value = "abc123"

            mock_app_builder_instance = MockAppBuilder.return_value
            mock_app_builder_instance.build_all.return_value = {}

            # rootfs 平台构建器 mock
            mock_mod = MagicMock()
            mock_mod.create_builder.return_value.build.return_value = {}
            mock_importlib.import_module.return_value = mock_mod

            engine = BuildEngine(config, project_dir=tmp_path)
            engine.build("rootfs")

            # AppBuilder 应在 rootfs 构建前被调用
            mock_app_builder_instance.build_all.assert_called_once()


# ---------------------------------------------------------------------------
# BuildCache app 组件哈希测试
# ---------------------------------------------------------------------------

class TestFlashConfigGeneration:
    """验证 BuildEngine 在 image 构建后生成 flash-config.json。"""

    def test_image_build_generates_flash_config(self, tmp_path):
        config = {
            "board": "test-board", "product": "default", "variant": "release",
            "arch": "aarch64", "platform": "rockchip", "soc": "rk3566",
            "flash_tool": "upgrade_tool",
            "rootfs": {"custom_packages": []},
            "partitions": {
                "format": "gpt", "sector_size": 512,
                "entries": [
                    {"name": "boot", "offset": "0x8000", "size": "0x20000", "type": "ext4"},
                    {"name": "rootfs", "offset": "0x40000", "size": "0x200000", "type": "ext4"},
                ],
            },
        }
        with (
            patch("builder.engine.DockerRunner"),
            patch("builder.engine.SourceManager"),
            patch("builder.engine.BuildCache") as MockCache,
            patch("builder.engine.AppBuilder") as MockAppBuilder,
            patch("builder.engine.importlib") as mock_importlib,
        ):
            mock_cache = MockCache.return_value
            mock_cache.is_up_to_date.return_value = False
            mock_cache.compute_hash.return_value = "abc"
            mock_cache.target_dir = tmp_path / "target" / "test-board" / "default" / "release"
            mock_cache.target_dir.mkdir(parents=True)

            mock_app = MockAppBuilder.return_value
            mock_app.build_all.return_value = {}

            mock_mod = MagicMock()
            mock_mod.create_builder.return_value.build.return_value = {}
            mock_importlib.import_module.return_value = mock_mod

            engine = BuildEngine(config, project_dir=tmp_path)
            engine.build("image")

            flash_json = mock_cache.target_dir / "flash-config.json"
            assert flash_json.exists()
            import json
            data = json.loads(flash_json.read_text())
            assert data["platform"] == "rockchip"
            partition_names = [p["name"] for p in data["partitions"]]
            assert "boot" in partition_names
            assert "rootfs" in partition_names

    def test_rootfs_build_does_not_generate_flash_config(self, tmp_path):
        config = {
            "board": "test-board", "product": "default", "variant": "release",
            "arch": "aarch64", "platform": "rockchip", "soc": "rk3566",
            "rootfs": {"custom_packages": []},
        }
        with (
            patch("builder.engine.DockerRunner"),
            patch("builder.engine.SourceManager"),
            patch("builder.engine.BuildCache") as MockCache,
            patch("builder.engine.AppBuilder") as MockAppBuilder,
            patch("builder.engine.importlib") as mock_importlib,
        ):
            mock_cache = MockCache.return_value
            mock_cache.is_up_to_date.return_value = False
            mock_cache.compute_hash.return_value = "abc"
            mock_cache.target_dir = tmp_path / "target" / "test-board" / "default" / "release"
            mock_cache.target_dir.mkdir(parents=True)

            mock_app = MockAppBuilder.return_value
            mock_app.build_all.return_value = {}

            mock_mod = MagicMock()
            mock_mod.create_builder.return_value.build.return_value = {}
            mock_importlib.import_module.return_value = mock_mod

            engine = BuildEngine(config, project_dir=tmp_path)
            engine.build("rootfs")

            flash_json = mock_cache.target_dir / "flash-config.json"
            assert not flash_json.exists()


class TestCacheInjection:
    """验证 BuildEngine 向 ComponentBuilder 注入 cache 引用。"""

    def test_builder_receives_cache(self, tmp_path):
        config = {
            "board": "test-board", "product": "default", "variant": "release",
            "arch": "aarch64", "platform": "rockchip", "soc": "rk3566",
            "rootfs": {"custom_packages": []},
        }
        with (
            patch("builder.engine.DockerRunner"),
            patch("builder.engine.SourceManager"),
            patch("builder.engine.BuildCache") as MockCache,
            patch("builder.engine.importlib") as mock_importlib,
        ):
            mock_cache = MockCache.return_value
            mock_cache.is_up_to_date.return_value = False
            mock_cache.compute_hash.return_value = "abc"

            mock_builder = MagicMock()
            mock_builder.build.return_value = {}
            mock_mod = MagicMock()
            mock_mod.create_builder.return_value = mock_builder
            mock_importlib.import_module.return_value = mock_mod

            engine = BuildEngine(config, project_dir=tmp_path)
            engine.build("kernel")

            assert mock_builder.cache is mock_cache


class TestBuildCacheApp:
    """验证 BuildCache.compute_hash 对 app 组件的哈希行为。"""

    def _make_cache(self, config: dict, tmpdir: str) -> BuildCache:
        cache = BuildCache.__new__(BuildCache)
        cache.config = config
        board = config["board"]
        product = config.get("product", "default")
        variant = config.get("variant", "release")
        cache.target_dir = Path(tmpdir) / board / product / variant
        return cache

    def test_app哈希可重复计算(self):
        """相同配置下，app 组件哈希应每次一致（幂等性）。"""
        config = {
            "board": "test", "product": "default", "variant": "release",
            "platform": "rockchip", "soc": "rk3566",
            "rootfs": {"custom_packages": []},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = self._make_cache(config, tmpdir)
            h1 = cache.compute_hash("app")
            h2 = cache.compute_hash("app")
            assert h1 == h2

    def test_custom_packages变化导致哈希改变(self):
        """custom_packages 列表变化时，app 哈希应发生变化。"""
        config1 = {
            "board": "test", "product": "default", "variant": "release",
            "platform": "rockchip", "soc": "rk3566",
            "rootfs": {"custom_packages": []},
        }
        config2 = {
            "board": "test", "product": "default", "variant": "release",
            "platform": "rockchip", "soc": "rk3566",
            "rootfs": {"custom_packages": ["mypkg"]},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            h1 = self._make_cache(config1, tmpdir).compute_hash("app")
            h2 = self._make_cache(config2, tmpdir).compute_hash("app")
            assert h1 != h2, "增加 custom_packages 条目后哈希应改变"

    def test_app_yaml内容变化导致哈希改变(self, tmp_path):
        """app.yaml 文件内容改变时，app 哈希应发生变化。"""
        import os

        config = {
            "board": "test", "product": "default", "variant": "release",
            "platform": "rockchip", "soc": "rk3566",
            "rootfs": {"custom_packages": ["mypkg"]},
        }

        # 在 tmp_path 下创建 app/mypkg/app.yaml，并在计算哈希时切换工作目录
        app_dir = tmp_path / "app" / "mypkg"
        app_dir.mkdir(parents=True)
        app_yaml = app_dir / "app.yaml"

        app_yaml.write_text("app:\n  name: mypkg\n  version: 1.0.0\n")

        with tempfile.TemporaryDirectory() as tmpdir:
            cache = self._make_cache(config, tmpdir)

            # 第一次：version 1.0.0
            orig_cwd = os.getcwd()
            os.chdir(tmp_path)
            try:
                h1 = cache.compute_hash("app")
                # 修改 app.yaml（版本变更）
                app_yaml.write_text("app:\n  name: mypkg\n  version: 2.0.0\n")
                h2 = cache.compute_hash("app")
            finally:
                os.chdir(orig_cwd)

        assert h1 != h2, "app.yaml 内容变更后哈希应改变"

    def test_app哈希与kernel哈希独立(self):
        """app 与 kernel 组件的哈希计算互不干扰。"""
        config = {
            "board": "test", "product": "default", "variant": "release",
            "platform": "rockchip", "soc": "rk3566",
            "rootfs": {"custom_packages": []},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = self._make_cache(config, tmpdir)
            h_app = cache.compute_hash("app")
            h_kernel = cache.compute_hash("kernel")
            assert h_app != h_kernel, "app 与 kernel 哈希应不同"

    def test_store_and_is_up_to_date_app组件(self):
        """store 后，app 组件应判定为最新（is_up_to_date 返回 True）。"""
        config = {
            "board": "test", "product": "default", "variant": "release",
            "platform": "rockchip", "soc": "rk3566",
            "rootfs": {"custom_packages": []},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = self._make_cache(config, tmpdir)
            assert not cache.is_up_to_date("app")
            cache.store("app")
            assert cache.is_up_to_date("app")
