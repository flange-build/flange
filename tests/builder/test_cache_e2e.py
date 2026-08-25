"""缓存系统端到端测试 — 模拟完整构建周期验证缓存命中矩阵。

覆盖场景：
- 首次构建：base miss + customize miss → 完整构建
- 改 overlay：base hit + customize miss → 只 Phase 2
- 无改动：base hit + customize hit → 全跳过
- 改 packages：base miss + customize miss → 完整重建
- 改 App 源码（非 app.yaml）：app hash 变 → deb 变 → customize miss → Phase 2
"""

import tempfile
from pathlib import Path

from builder.cache import BuildCache


class TestCacheE2E:
    """模拟构建周期，验证缓存命中矩阵。"""

    def _make_env(
        self,
        tmpdir: str,
        packages=None,
        custom_packages=None,
        rootfs_url="https://example.com/ubuntu-base.tar.gz",
        kernel=None,
    ):
        """构造测试环境：config + cache + 目录结构。"""
        config = {
            "board": "test", "platform": "rockchip",
            "soc": "rk3566",
            "architecture": {
                "userspace": "aarch64", "kernel": "arm64", "bootloader": "arm",
            },
            "product": "default", "variant": "release",
            "rootfs": {
                "url": rootfs_url,
                "packages": (packages if packages is not None
                             else ["systemd", "openssh-server"]),
                "custom_packages": (custom_packages
                                    if custom_packages is not None else []),
            },
        }
        if kernel is not None:
            config["kernel"] = {
                "device_tree": {"directory": "", "name": "test"},
                **kernel,
            }
        else:
            config["kernel"] = {
                "device_tree": {"directory": "", "name": "test"},
            }
        cache = BuildCache(
            config,
            target_base=Path(tmpdir) / ".build" / "target",
            project_root=Path(tmpdir),
        )
        return config, cache

    @staticmethod
    def _create_rootfs_artifact(cache: BuildCache) -> None:
        rootfs_dir = cache.target_dir / "rootfs"
        rootfs_dir.mkdir(parents=True, exist_ok=True)
        (rootfs_dir / "rootfs.img").write_bytes(b"rootfs")

    @staticmethod
    def _create_kernel_artifacts(cache: BuildCache) -> None:
        kernel_dir = cache.target_dir / "kernel"
        kernel_dir.mkdir(parents=True, exist_ok=True)
        (kernel_dir / "Image").write_bytes(b"kernel")
        (kernel_dir / "test.dtb").write_bytes(b"dtb")

    def test_first_build_all_miss(self):
        """首次构建：所有哈希都是 miss。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config, cache = self._make_env(tmpdir)

            assert not cache.is_up_to_date("rootfs")
            assert not cache.is_phase_up_to_date("rootfs", "base")

            # 模拟构建完成
            cache.store_phase("rootfs", "base")
            cache.store("rootfs")
            self._create_rootfs_artifact(cache)

            assert cache.is_up_to_date("rootfs")
            assert cache.is_phase_up_to_date("rootfs", "base")

    def test_overlay_change_base_hit_customize_miss(self):
        """改 overlay 文件：base hit，customize miss。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            overlay_dir = (Path(tmpdir) / "components" / "board" / "test"
                           / "overlay")
            overlay_dir.mkdir(parents=True)
            (overlay_dir / "hosts").write_text("127.0.0.1 localhost")

            _config, cache = self._make_env(tmpdir)
            cache.store_phase("rootfs", "base")
            cache.store("rootfs")
            self._create_rootfs_artifact(cache)
            assert cache.is_up_to_date("rootfs")
            assert cache.is_phase_up_to_date("rootfs", "base")

            (overlay_dir / "hosts").write_text("127.0.0.1 myhost")
            _changed_config, changed = self._make_env(tmpdir)

            assert changed.is_phase_up_to_date("rootfs", "base")
            assert not changed.is_up_to_date("rootfs")

    def test_no_change_all_hit(self):
        """无改动：全部 hit。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config, cache = self._make_env(tmpdir)
            cache.store_phase("rootfs", "base")
            cache.store("rootfs")
            self._create_rootfs_artifact(cache)

            assert cache.is_phase_up_to_date("rootfs", "base")
            assert cache.is_up_to_date("rootfs")

    def test_packages_change_all_miss(self):
        """改 packages：base miss → customize 也 miss。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config, cache = self._make_env(tmpdir, packages=["systemd"])
            cache.store_phase("rootfs", "base")
            cache.store("rootfs")
            self._create_rootfs_artifact(cache)

            assert cache.is_phase_up_to_date("rootfs", "base")
            assert cache.is_up_to_date("rootfs")

            _changed_config, changed = self._make_env(
                tmpdir, packages=["systemd", "vim"])

            assert not changed.is_phase_up_to_date("rootfs", "base")
            assert not changed.is_up_to_date("rootfs")

    def test_app_source_change_triggers_customize_miss(self):
        """改 App 源码 → app hash 变 → Merkle 级联使 rootfs miss。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir) / "components" / "app" / "myapp"
            app_dir.mkdir(parents=True)
            (app_dir / "app.yaml").write_text("name: myapp")
            (app_dir / "main.sh").write_text("#!/bin/bash\necho hello")

            _config, cache = self._make_env(
                tmpdir, custom_packages=["myapp"])
            app_hash_1 = cache.compute_hash("app")
            app_output = cache.target_dir / "app" / "myapp_1.0_arm64.deb"
            app_output.parent.mkdir(parents=True)
            app_output.write_bytes(b"deb")
            cache.store("app")
            cache.store_phase("rootfs", "base")
            cache.store("rootfs")
            self._create_rootfs_artifact(cache)

            assert cache.is_up_to_date("app")
            assert cache.is_phase_up_to_date("rootfs", "base")
            assert cache.is_up_to_date("rootfs")

            (app_dir / "main.sh").write_text("#!/bin/bash\necho world")
            _changed_config, changed = self._make_env(
                tmpdir, custom_packages=["myapp"])
            assert app_hash_1 != changed.compute_hash("app")
            assert not changed.is_up_to_date("app")
            assert changed.is_phase_up_to_date("rootfs", "base")
            assert not changed.is_up_to_date("rootfs")

    def test_kernel_change_invalidates_rootfs(self):
        """改 kernel config → kernel 与消费 modules 的 rootfs 都失效。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            _config, cache = self._make_env(
                tmpdir, kernel={"defconfig": ["defconfig_a"]})

            self._create_kernel_artifacts(cache)
            cache.store("kernel")
            cache.store_phase("rootfs", "base")
            cache.store("rootfs")
            self._create_rootfs_artifact(cache)

            assert cache.is_up_to_date("kernel")
            assert cache.is_up_to_date("rootfs")

            _changed_config, changed = self._make_env(
                tmpdir, kernel={"defconfig": ["defconfig_b"]})

            assert not changed.is_up_to_date("kernel")
            assert changed.is_phase_up_to_date("rootfs", "base")
            assert not changed.is_up_to_date("rootfs")

    def test_url_change_invalidates_base(self):
        """改 rootfs.url → base miss → customize 也 miss。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config, cache = self._make_env(tmpdir)
            cache.store_phase("rootfs", "base")
            cache.store("rootfs")
            self._create_rootfs_artifact(cache)

            _changed_config, changed = self._make_env(
                tmpdir,
                rootfs_url="https://example.com/other-base.tar.gz",
            )

            assert not changed.is_phase_up_to_date("rootfs", "base")
            assert not changed.is_up_to_date("rootfs")
