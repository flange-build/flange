"""缓存系统端到端测试 — 模拟完整构建周期验证缓存命中矩阵。

覆盖场景：
- 首次构建：base miss + customize miss → 完整构建
- 改 overlay：base hit + customize miss → 只 Phase 2
- 无改动：base hit + customize hit → 全跳过
- 改 packages：base miss + customize miss → 完整重建
- 改 App 源码（非 app.yaml）：app hash 变 → deb 变 → customize miss → Phase 2
"""

import hashlib
import json
import os
import tempfile
from pathlib import Path

from builder.cache import BuildCache


class TestCacheE2E:
    """模拟构建周期，验证缓存命中矩阵。"""

    def _make_env(self, tmpdir: str, packages=None, custom_packages=None):
        """构造测试环境：config + cache + 目录结构。"""
        config = {
            "board": "test", "platform": "rockchip",
            "soc": "rk3566", "arch": "aarch64",
            "rootfs": {
                "url": "https://example.com/ubuntu-base.tar.gz",
                "packages": packages or ["systemd", "openssh-server"],
                "custom_packages": custom_packages or [],
            },
        }
        cache = BuildCache(config, target_base=Path(tmpdir) / "target")
        return config, cache

    def test_first_build_all_miss(self):
        """首次构建：所有哈希都是 miss。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config, cache = self._make_env(tmpdir)

            assert not cache.is_up_to_date("rootfs")
            assert not cache.is_phase_up_to_date("rootfs", "base")

            # 模拟构建完成
            cache.store_phase("rootfs", "base")
            cache.store("rootfs")

            assert cache.is_up_to_date("rootfs")
            assert cache.is_phase_up_to_date("rootfs", "base")

    def test_overlay_change_base_hit_customize_miss(self):
        """改 overlay 文件：base hit，customize miss。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            overlay_dir = Path(tmpdir) / "board" / "test" / "overlay"
            overlay_dir.mkdir(parents=True)
            (overlay_dir / "hosts").write_text("127.0.0.1 localhost")

            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                config, cache = self._make_env(tmpdir)

                # 首次构建
                cache.store_phase("rootfs", "base")
                cache.store("rootfs")
                assert cache.is_up_to_date("rootfs")
                assert cache.is_phase_up_to_date("rootfs", "base")

                # 改 overlay
                (overlay_dir / "hosts").write_text("127.0.0.1 myhost")

                # base 仍然命中（overlay 不影响 base）
                assert cache.is_phase_up_to_date("rootfs", "base")
                # customize 失效（overlay 影响 customize）
                assert not cache.is_up_to_date("rootfs")
            finally:
                os.chdir(old_cwd)

    def test_no_change_all_hit(self):
        """无改动：全部 hit。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config, cache = self._make_env(tmpdir)
            cache.store_phase("rootfs", "base")
            cache.store("rootfs")

            assert cache.is_phase_up_to_date("rootfs", "base")
            assert cache.is_up_to_date("rootfs")

    def test_packages_change_all_miss(self):
        """改 packages：base miss → customize 也 miss。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config, cache = self._make_env(tmpdir, packages=["systemd"])
            cache.store_phase("rootfs", "base")
            cache.store("rootfs")

            assert cache.is_phase_up_to_date("rootfs", "base")
            assert cache.is_up_to_date("rootfs")

            # 改 packages
            cache.config["rootfs"]["packages"] = ["systemd", "vim"]

            assert not cache.is_phase_up_to_date("rootfs", "base")
            assert not cache.is_up_to_date("rootfs")

    def test_app_source_change_triggers_customize_miss(self):
        """改 App 源码 → app hash 变 → deb 重建 → customize miss。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir) / "app" / "myapp"
            app_dir.mkdir(parents=True)
            (app_dir / "app.yaml").write_text("name: myapp")
            (app_dir / "main.sh").write_text("#!/bin/bash\necho hello")

            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                config, cache = self._make_env(tmpdir, custom_packages=["myapp"])

                # 模拟 app 构建产出 deb
                deb_dir = cache.target_dir / "app"
                deb_dir.mkdir(parents=True)
                (deb_dir / "myapp_1.0_arm64.deb").write_bytes(b"deb-v1")

                # 存储缓存
                app_hash_1 = cache.compute_hash("app")
                cache.store("app")
                cache.store_phase("rootfs", "base")
                cache.store("rootfs")

                assert cache.is_up_to_date("app")
                assert cache.is_phase_up_to_date("rootfs", "base")
                assert cache.is_up_to_date("rootfs")

                # 改 App 源码
                (app_dir / "main.sh").write_text("#!/bin/bash\necho world")
                app_hash_2 = cache.compute_hash("app")
                assert app_hash_1 != app_hash_2
                assert not cache.is_up_to_date("app")

                # 模拟 app 重建，产出新 deb
                (deb_dir / "myapp_1.0_arm64.deb").write_bytes(b"deb-v2")

                # base 仍命中
                assert cache.is_phase_up_to_date("rootfs", "base")
                # customize 失效（deb 内容变了）
                assert not cache.is_up_to_date("rootfs")
            finally:
                os.chdir(old_cwd)

    def test_kernel_change_does_not_affect_rootfs(self):
        """改 kernel config → rootfs 不受影响。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config, cache = self._make_env(tmpdir)
            config["kernel"] = {"defconfig": "defconfig_a"}

            cache.store("kernel")
            cache.store_phase("rootfs", "base")
            cache.store("rootfs")

            assert cache.is_up_to_date("kernel")
            assert cache.is_up_to_date("rootfs")

            # 改 kernel config
            cache.config["kernel"] = {"defconfig": "defconfig_b"}

            assert not cache.is_up_to_date("kernel")
            # rootfs 不受影响
            assert cache.is_phase_up_to_date("rootfs", "base")
            assert cache.is_up_to_date("rootfs")

    def test_url_change_invalidates_base(self):
        """改 rootfs.url → base miss → customize 也 miss。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config, cache = self._make_env(tmpdir)
            cache.store_phase("rootfs", "base")
            cache.store("rootfs")

            cache.config["rootfs"]["url"] = "https://example.com/other-base.tar.gz"

            assert not cache.is_phase_up_to_date("rootfs", "base")
            assert not cache.is_up_to_date("rootfs")
