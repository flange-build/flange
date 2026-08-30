"""BuildCache 测试 — 验证内容哈希的增量判断逻辑。"""

import hashlib
import json
import tempfile
from pathlib import Path
from builder.cache import BuildCache
from builder.source import SourceManager


def _snapshot_store(cache, prefix: str = "rootfs-base-"):
    """与 builder/rootfs.py 同构地解析 base 快照目录。"""
    from builder.snapshot import SnapshotStore

    return SnapshotStore(
        cache.target_dir.parent.parent.parent / ".cache", prefix, None)


def _snapshot_name(cache, component: str = "rootfs") -> str:
    """生产判据：base 快照按内容哈希命名，命中与否就是同名文件在不在。

    因此不存在独立的 ``.base_hash`` 记录文件 —— 文件名本身就是那条记录。
    这里直接比对文件名，测的就是 builder/rootfs.py 与 builder/recovery.py
    实际走的那条路径。
    """
    return cache.compute_phase_hash(component, "base")


_ARCHITECTURE = {
    "userspace": "aarch64", "kernel": "arm64", "bootloader": "arm64",
}


class TestBuildCache:
    def _make_cache(self, config: dict, tmpdir: str) -> BuildCache:
        config.setdefault("architecture", _ARCHITECTURE)
        config.setdefault("kernel", {}).setdefault(
            "device_tree", {"directory": "", "name": "test"})
        return BuildCache(
            config,
            target_base=Path(tmpdir),
            project_root=Path(tmpdir),
        )

    @staticmethod
    def _create_kernel_artifacts(cache: BuildCache) -> None:
        kernel_dir = cache.target_dir / "kernel"
        kernel_dir.mkdir(parents=True, exist_ok=True)
        (kernel_dir / "Image").write_bytes(b"kernel")
        (kernel_dir / "test.dtb").write_bytes(b"dtb")

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
            self._create_kernel_artifacts(cache)
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
            self._create_kernel_artifacts(cache1)
            cache1.store("kernel")
            cache2 = self._make_cache(config2, tmpdir)
            assert not cache2.is_up_to_date("kernel")

    def test_different_components_independent(self):
        config = {"board": "test", "product": "default", "variant": "release",
                  "platform": "rockchip", "soc": "rk3566"}
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = self._make_cache(config, tmpdir)
            self._create_kernel_artifacts(cache)
            cache.store("kernel")
            assert cache.is_up_to_date("kernel")
            assert not cache.is_up_to_date("bootloader")

    def test_branch_tracked_named_repo_bypasses_cache_and_hashes_head(
            self, tmp_path):
        config = {
            "board": "test", "product": "default", "variant": "release",
            "platform": "test", "soc": "test",
            "architecture": _ARCHITECTURE,
            "sources": {
                "kernel": {
                    "url": "https://example.com/kernel.git",
                    "branch": "main",
                },
            },
            "kernel": {
                "source": {"name": "kernel"},
                "device_tree": {"directory": "", "name": "test"},
            },
        }
        repo_dir = (
            tmp_path / ".build" / "sources" / "repos"
            / SourceManager.source_identity(config["sources"]["kernel"])
        )
        repo_dir.mkdir(parents=True)
        cache = BuildCache(config, target_base=tmp_path / "target",
                           project_root=tmp_path)
        seen = []
        cache._git_head = lambda path: seen.append(path) or "branch-head"

        cache.compute_hash("kernel")

        assert seen == [repo_dir]
        assert not cache.is_up_to_date("kernel")


class TestBootloaderArtifactCache:
    """bootloader 缓存产物校验。"""

    def test_allwinnera733_bootloader使用allwinner产物判断缓存命中(self, tmp_path):
        """A733 bootloader 产物存在且 hash 匹配时应读取上次构建状态。"""
        config = {
            "board": "radxa-cubie-a7z",
            "product": "default",
            "variant": "debug",
            "architecture": _ARCHITECTURE,
            "platform": "allwinnera733",
            "soc": "a733",
            "bootloader": {"target": "radxa-cubie-a7z"},
        }
        cache = BuildCache(config, target_base=tmp_path)
        bootloader_dir = cache.target_dir / "bootloader"
        bootloader_dir.mkdir(parents=True)
        for name in ("boot0_sdcard.bin", "boot0_ufs.bin", "boot_package.fex"):
            (bootloader_dir / name).write_bytes(b"fake")
        (bootloader_dir / ".build_hash").write_text(cache.compute_hash("bootloader"))

        assert cache.is_up_to_date("bootloader")


class TestDirectoryHash:
    """_hash_directory 工具方法测试。"""

    def _make_cache(self) -> BuildCache:
        cache = BuildCache.__new__(BuildCache)
        cache.config = {"board": "test", "platform": "rockchip",
                        "soc": "rk3566", "architecture": _ARCHITECTURE}
        return cache

    def _compute(self, cache: BuildCache, directory: Path) -> str:
        h = hashlib.sha256()
        cache._hash_directory(h, directory)
        return h.hexdigest()

    def test_empty_directory(self):
        cache = self._make_cache()
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir) / "empty"
            d.mkdir()
            h1 = self._compute(cache, d)
            h2 = self._compute(cache, d)
            assert h1 == h2

    def test_file_content_change(self):
        cache = self._make_cache()
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir) / "dir"
            d.mkdir()
            (d / "a.txt").write_text("hello")
            h1 = self._compute(cache, d)
            (d / "a.txt").write_text("world")
            h2 = self._compute(cache, d)
            assert h1 != h2

    def test_filename_change(self):
        cache = self._make_cache()
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir) / "dir"
            d.mkdir()
            (d / "a.txt").write_text("hello")
            h1 = self._compute(cache, d)
            (d / "a.txt").unlink()
            (d / "b.txt").write_text("hello")
            h2 = self._compute(cache, d)
            assert h1 != h2

    def test_excludes_pycache(self):
        cache = self._make_cache()
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir) / "dir"
            d.mkdir()
            (d / "main.py").write_text("print(1)")
            h1 = self._compute(cache, d)
            pycache = d / "__pycache__"
            pycache.mkdir()
            (pycache / "main.cpython-310.pyc").write_bytes(b"\x00\x01")
            h2 = self._compute(cache, d)
            assert h1 == h2

    def test_excludes_git_dir(self):
        cache = self._make_cache()
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir) / "dir"
            d.mkdir()
            (d / "src.c").write_text("int main(){}")
            h1 = self._compute(cache, d)
            git = d / ".git"
            git.mkdir()
            (git / "HEAD").write_text("ref: refs/heads/main")
            h2 = self._compute(cache, d)
            assert h1 == h2

    def test_excludes_build_dir(self):
        cache = self._make_cache()
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir) / "dir"
            d.mkdir()
            (d / "src.c").write_text("int main(){}")
            h1 = self._compute(cache, d)
            build = d / "build"
            build.mkdir()
            (build / "output.bin").write_bytes(b"\xff")
            h2 = self._compute(cache, d)
            assert h1 == h2

    def test_excludes_pyc_extension(self):
        cache = self._make_cache()
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir) / "dir"
            d.mkdir()
            (d / "main.py").write_text("print(1)")
            h1 = self._compute(cache, d)
            (d / "main.pyc").write_bytes(b"\x00")
            h2 = self._compute(cache, d)
            assert h1 == h2

    def test_excludes_dot_o_extension(self):
        cache = self._make_cache()
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir) / "dir"
            d.mkdir()
            (d / "foo.c").write_text("void foo(){}")
            h1 = self._compute(cache, d)
            (d / "foo.o").write_bytes(b"\x7fELF")
            h2 = self._compute(cache, d)
            assert h1 == h2

    def test_sorted_order_stable(self):
        """文件创建顺序不影响哈希（按路径排序）。"""
        cache = self._make_cache()
        with tempfile.TemporaryDirectory() as tmpdir:
            d1 = Path(tmpdir) / "d1"
            d1.mkdir()
            (d1 / "b.txt").write_text("B")
            (d1 / "a.txt").write_text("A")
            h1 = self._compute(cache, d1)

            d2 = Path(tmpdir) / "d2"
            d2.mkdir()
            (d2 / "a.txt").write_text("A")
            (d2 / "b.txt").write_text("B")
            h2 = self._compute(cache, d2)
            assert h1 == h2

    def test_new_file_changes_hash(self):
        cache = self._make_cache()
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir) / "dir"
            d.mkdir()
            (d / "a.txt").write_text("A")
            h1 = self._compute(cache, d)
            (d / "b.txt").write_text("B")
            h2 = self._compute(cache, d)
            assert h1 != h2

    def test_nested_directory(self):
        """子目录下的文件也被 hash。"""
        cache = self._make_cache()
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir) / "dir"
            d.mkdir()
            sub = d / "sub"
            sub.mkdir()
            (sub / "file.txt").write_text("nested")
            h1 = self._compute(cache, d)
            (sub / "file.txt").write_text("changed")
            h2 = self._compute(cache, d)
            assert h1 != h2


class TestAppSourceHash:
    """App 源码递归哈希测试 — 通过公开 compute_hash 接口验证。"""

    def _make_cache(
        self,
        tmpdir: str,
        custom_packages: list,
        external_apps: dict | None = None,
    ) -> BuildCache:
        config = {
            "board": "test", "platform": "rockchip",
            "soc": "rk3566", "architecture": _ARCHITECTURE,
            "product": "default", "variant": "release",
            "rootfs": {"custom_packages": custom_packages},
        }
        if external_apps:
            config["external_apps"] = external_apps
        return BuildCache(
            config,
            target_base=Path(tmpdir) / ".build" / "target",
            project_root=Path(tmpdir),
        )

    @staticmethod
    def _app_dir(tmpdir: str, name: str) -> Path:
        return Path(tmpdir) / "components" / "app" / name

    def _compute_app_hash(self, cache: BuildCache) -> str:
        return cache.compute_hash("app")

    def test_source_file_change(self):
        """App 源码文件变化 → 哈希变化（修复验证）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = self._app_dir(tmpdir, "myapp")
            app_dir.mkdir(parents=True)
            (app_dir / "app.yaml").write_text("name: myapp")
            (app_dir / "conf").mkdir()
            (app_dir / "conf" / "config.txt").write_text("key=value1")

            h1 = self._compute_app_hash(
                self._make_cache(tmpdir, ["myapp"]))
            (app_dir / "conf" / "config.txt").write_text("key=value2")
            h2 = self._compute_app_hash(
                self._make_cache(tmpdir, ["myapp"]))
            assert h1 != h2

    def test_app_yaml_change(self):
        """app.yaml 变化 → 哈希变化（回归保护）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = self._app_dir(tmpdir, "myapp")
            app_dir.mkdir(parents=True)
            (app_dir / "app.yaml").write_text("name: myapp\nversion: 1.0")

            h1 = self._compute_app_hash(
                self._make_cache(tmpdir, ["myapp"]))
            (app_dir / "app.yaml").write_text("name: myapp\nversion: 2.0")
            h2 = self._compute_app_hash(
                self._make_cache(tmpdir, ["myapp"]))
            assert h1 != h2

    def test_external_local_firmware_change(self):
        """package-local firmware 变化应使 app deb 缓存失效。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir) / "components/packages/demo-firmware"
            app_dir.mkdir(parents=True)
            (app_dir / "app.yaml").write_text("name: demo-firmware")
            blob = app_dir / "topology.bin"
            blob.write_bytes(b"version-1")
            external_apps = {
                "demo-firmware": {"local_path": str(app_dir)}
            }

            h1 = self._compute_app_hash(self._make_cache(
                tmpdir, ["demo-firmware"], external_apps))
            blob.write_bytes(b"version-2")
            h2 = self._compute_app_hash(self._make_cache(
                tmpdir, ["demo-firmware"], external_apps))

            assert h1 != h2

    def test_new_file_changes_hash(self):
        """新增 App 文件 → 哈希变化。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = self._app_dir(tmpdir, "myapp")
            app_dir.mkdir(parents=True)
            (app_dir / "app.yaml").write_text("name: myapp")

            h1 = self._compute_app_hash(
                self._make_cache(tmpdir, ["myapp"]))
            (app_dir / "newfile.sh").write_text("#!/bin/bash")
            h2 = self._compute_app_hash(
                self._make_cache(tmpdir, ["myapp"]))
            assert h1 != h2

    def test_pycache_excluded(self):
        """__pycache__ 不影响哈希。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = self._app_dir(tmpdir, "myapp")
            app_dir.mkdir(parents=True)
            (app_dir / "app.yaml").write_text("name: myapp")

            h1 = self._compute_app_hash(
                self._make_cache(tmpdir, ["myapp"]))
            pycache = app_dir / "__pycache__"
            pycache.mkdir()
            (pycache / "mod.cpython-310.pyc").write_bytes(b"\x00")
            h2 = self._compute_app_hash(
                self._make_cache(tmpdir, ["myapp"]))
            assert h1 == h2

    def test_custom_packages_list_change(self):
        """custom_packages 列表变化 → 哈希变化。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ("app1", "app2"):
                d = self._app_dir(tmpdir, name)
                d.mkdir(parents=True)
                (d / "app.yaml").write_text(f"name: {name}")

            h1 = self._compute_app_hash(
                self._make_cache(tmpdir, ["app1"]))
            h2 = self._compute_app_hash(
                self._make_cache(tmpdir, ["app1", "app2"]))
            assert h1 != h2

    def test_missing_app_uses_placeholder(self):
        """缺失 App 目录使用占位符。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = self._make_cache(tmpdir, ["nonexistent"])
            assert self._compute_app_hash(cache)


class TestRootfsPhaseHash:
    """Rootfs 分阶段哈希测试。"""

    def _make_cache(self, tmpdir: str, **overrides) -> BuildCache:
        config = {
            "board": "test", "platform": "rockchip",
            "soc": "rk3566", "architecture": _ARCHITECTURE,
            "product": "default", "variant": "release",
            "rootfs": {
                "url": "https://example.com/ubuntu-base.tar.gz",
                "packages": ["systemd", "openssh-server"],
                "custom_packages": [],
            },
        }
        config.update(overrides)
        return BuildCache(
            config,
            target_base=Path(tmpdir) / ".build" / "target",
            project_root=Path(tmpdir),
        )

    def test_base_hash_depends_on_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache1 = self._make_cache(tmpdir)
            h1 = cache1.compute_phase_hash("rootfs", "base")

            cache2 = self._make_cache(tmpdir, rootfs={
                "url": "https://example.com/other.tar.gz",
                "packages": ["systemd", "openssh-server"],
                "custom_packages": [],
            })
            h2 = cache2.compute_phase_hash("rootfs", "base")
            assert h1 != h2

    def test_base_hash_depends_on_packages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache1 = self._make_cache(tmpdir)
            h1 = cache1.compute_phase_hash("rootfs", "base")

            cache2 = self._make_cache(tmpdir, rootfs={
                "url": "https://example.com/ubuntu-base.tar.gz",
                "packages": ["systemd", "openssh-server", "vim"],
                "custom_packages": [],
            })
            h2 = cache2.compute_phase_hash("rootfs", "base")
            assert h1 != h2

    def test_base_hash_depends_on_arch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache1 = self._make_cache(tmpdir)
            h1 = cache1.compute_phase_hash("rootfs", "base")

            cache2 = self._make_cache(tmpdir, architecture={
                "userspace": "armhf", "kernel": "arm",
                "bootloader": "arm",
            })
            h2 = cache2.compute_phase_hash("rootfs", "base")
            assert h1 != h2

    def test_base_hash_stable_with_package_order(self):
        """packages 排序后 hash，顺序不影响。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache1 = self._make_cache(tmpdir, rootfs={
                "url": "https://example.com/ubuntu-base.tar.gz",
                "packages": ["openssh-server", "systemd"],
                "custom_packages": [],
            })
            cache2 = self._make_cache(tmpdir, rootfs={
                "url": "https://example.com/ubuntu-base.tar.gz",
                "packages": ["systemd", "openssh-server"],
                "custom_packages": [],
            })
            assert cache1.compute_phase_hash(
                "rootfs", "base") == cache2.compute_phase_hash(
                    "rootfs", "base")

    def test_customize_hash_includes_base_hash(self):
        """packages 变化 → base_hash 变 → customize_hash 也变（级联）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache1 = self._make_cache(tmpdir)
            h1 = cache1.compute_hash("rootfs")

            cache2 = self._make_cache(tmpdir, rootfs={
                "url": "https://example.com/ubuntu-base.tar.gz",
                "packages": ["systemd", "openssh-server", "vim"],
                "custom_packages": [],
            })
            h2 = cache2.compute_hash("rootfs")
            assert h1 != h2

    def test_customize_hash_depends_on_overlay(self):
        """overlay 文件变化 → customize_hash 变，base_hash 不变。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            board_dir = (Path(tmpdir) / "components" / "board" / "test"
                         / "overlay")
            board_dir.mkdir(parents=True)
            (board_dir / "etc_hosts").write_text("127.0.0.1 localhost")

            cache1 = self._make_cache(tmpdir)
            h1_base = cache1.compute_phase_hash("rootfs", "base")
            h1_cust = cache1.compute_hash("rootfs")

            (board_dir / "etc_hosts").write_text("127.0.0.1 myhost")
            cache2 = self._make_cache(tmpdir)
            h2_base = cache2.compute_phase_hash("rootfs", "base")
            h2_cust = cache2.compute_hash("rootfs")

            assert h1_base == h2_base
            assert h1_cust != h2_cust

    def test_customize_hash_depends_on_app_sources(self):
        """App 源码变化经 Merkle 依赖使 rootfs hash 变化，base 不变。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            rootfs = {
                "url": "https://example.com/ubuntu-base.tar.gz",
                "packages": ["systemd"],
                "custom_packages": ["myapp"],
            }
            app_dir = (Path(tmpdir) / "components" / "app" / "myapp")
            app_dir.mkdir(parents=True)
            (app_dir / "app.yaml").write_text("name: myapp\nversion: 1")

            cache1 = self._make_cache(tmpdir, rootfs=rootfs)
            h1_base = cache1.compute_phase_hash("rootfs", "base")
            h1_cust = cache1.compute_hash("rootfs")

            (app_dir / "app.yaml").write_text("name: myapp\nversion: 2")
            cache2 = self._make_cache(tmpdir, rootfs=rootfs)
            h2_base = cache2.compute_phase_hash("rootfs", "base")
            h2_cust = cache2.compute_hash("rootfs")

            assert h1_base == h2_base
            assert h1_cust != h2_cust

    def test_customize_hash_depends_on_custom_packages_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache1 = self._make_cache(tmpdir, rootfs={
                "url": "https://example.com/ubuntu-base.tar.gz",
                "packages": ["systemd"],
                "custom_packages": ["app1"],
            })
            cache2 = self._make_cache(tmpdir, rootfs={
                "url": "https://example.com/ubuntu-base.tar.gz",
                "packages": ["systemd"],
                "custom_packages": ["app1", "app2"],
            })
            assert cache1.compute_hash("rootfs") != cache2.compute_hash("rootfs")

    def test_compute_hash_rootfs_is_stable(self):
        """相同输入下公开 rootfs hash 在不同缓存实例间稳定。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            h1 = self._make_cache(tmpdir).compute_hash("rootfs")
            h2 = self._make_cache(tmpdir).compute_hash("rootfs")
            assert h1 == h2
            assert len(h1) == 16


class TestPhaseCache:
    """分阶段缓存接口测试。"""

    def _make_cache(
        self,
        tmpdir: str,
        packages: list[str] | None = None,
    ) -> BuildCache:
        config = {
            "board": "test", "platform": "rockchip",
            "soc": "rk3566", "architecture": _ARCHITECTURE,
            "product": "default", "variant": "release",
            "rootfs": {
                "url": "https://example.com/ubuntu-base.tar.gz",
                "packages": packages or ["systemd"],
                "custom_packages": [],
            },
        }
        return BuildCache(
            config,
            target_base=Path(tmpdir) / ".build" / "target",
            project_root=Path(tmpdir),
        )

    @staticmethod
    def _create_rootfs_artifact(cache: BuildCache) -> None:
        rootfs_dir = cache.target_dir / "rootfs"
        rootfs_dir.mkdir(parents=True, exist_ok=True)
        (rootfs_dir / "rootfs.img").write_bytes(b"rootfs")

    def test_首次构建时快照不存在_保存后按同名命中(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = self._make_cache(tmpdir)
            store = _snapshot_store(cache)
            snapshot = store.resolve(_snapshot_name(cache))
            assert not snapshot.exists()

            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_bytes(b"snapshot")

            assert store.resolve(_snapshot_name(cache)).exists()

    def test_phase_hash_change_invalidates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = self._make_cache(tmpdir)
            _saved = _snapshot_name(cache)
            assert _snapshot_name(cache) == _saved

            # 改 packages → base_hash 变
            changed = self._make_cache(tmpdir, ["systemd", "vim"])
            assert _snapshot_name(changed) != _saved

    def test_different_phases_independent(self):
        """base 和 build 哈希互不影响。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = self._make_cache(tmpdir)
            _saved = _snapshot_name(cache)
            cache.store("rootfs")  # 写 .build_hash
            self._create_rootfs_artifact(cache)

            assert _snapshot_name(cache) == _saved
            assert cache.is_up_to_date("rootfs")

            # 改 packages → base 和 build 都失效
            changed = self._make_cache(tmpdir, ["systemd", "vim"])
            assert _snapshot_name(changed) != _saved
            assert not changed.is_up_to_date("rootfs")

    def test_compute_phase_hash_is_stable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            h1 = self._make_cache(tmpdir).compute_phase_hash("rootfs", "base")
            h2 = self._make_cache(tmpdir).compute_phase_hash("rootfs", "base")
            assert h1 == h2
            assert len(h1) == 16

    def test_unsupported_phase_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = self._make_cache(tmpdir)
            try:
                cache.compute_phase_hash("kernel", "base")
                assert False, "应该抛出 ValueError"
            except ValueError:
                pass
