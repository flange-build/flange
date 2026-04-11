"""BuildCache 测试 — 验证内容哈希的增量判断逻辑。"""

import json
import tempfile
from pathlib import Path
from builder.cache import BuildCache


class TestBuildCache:
    def _make_cache(self, config: dict, tmpdir: str) -> BuildCache:
        cache = BuildCache.__new__(BuildCache)
        cache.config = config
        board = config["board"]
        product = config.get("product", "default")
        variant = config.get("variant", "release")
        cache.target_dir = Path(tmpdir) / board / product / variant
        return cache

    def test_not_up_to_date_when_no_hash_file(self):
        config = {"board": "test", "product": "default", "variant": "release",
                  "platform": "rockchip", "soc": "rk3566"}
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = self._make_cache(config, tmpdir)
            assert not cache.is_up_to_date("kernel")

    def test_up_to_date_after_store(self):
        config = {"board": "test", "product": "default", "variant": "release",
                  "platform": "rockchip", "soc": "rk3566"}
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = self._make_cache(config, tmpdir)
            cache.store("kernel")
            assert cache.is_up_to_date("kernel")

    def test_not_up_to_date_when_config_changes(self):
        config1 = {"board": "test", "product": "default", "variant": "release",
                   "platform": "rockchip", "soc": "rk3566",
                   "kernel": {"defconfig": "defconfig_a"}}
        config2 = {"board": "test", "product": "default", "variant": "release",
                   "platform": "rockchip", "soc": "rk3566",
                   "kernel": {"defconfig": "defconfig_b"}}
        with tempfile.TemporaryDirectory() as tmpdir:
            cache1 = self._make_cache(config1, tmpdir)
            cache1.store("kernel")
            cache2 = self._make_cache(config2, tmpdir)
            assert not cache2.is_up_to_date("kernel")

    def test_different_components_independent(self):
        config = {"board": "test", "product": "default", "variant": "release",
                  "platform": "rockchip", "soc": "rk3566"}
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = self._make_cache(config, tmpdir)
            cache.store("kernel")
            assert cache.is_up_to_date("kernel")
            assert not cache.is_up_to_date("bootloader")
