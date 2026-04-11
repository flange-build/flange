"""Rockchip Rootfs 构建策略 -- 替代 build_base.sh + build_customize.sh

支持两阶段独立缓存：
- Phase 1 (Base): 解压 tarball + apt install → 缓存为 base.tar.gz 快照
- Phase 2 (Customize): overlay + custom debs → 最终 rootfs.tar.gz
"""

import shutil
import tempfile
from pathlib import Path
from builder.base import ComponentBuilder
from builder.chroot import ChrootContext


class RockchipRootfsBuilder(ComponentBuilder):
    component = "rootfs"

    def build(self, config: dict) -> dict:
        """rootfs 无需克隆源码仓库，跳过 source.ensure / reset / patch。"""
        self.compile(None, config)
        return self.collect(None, config)

    def configure(self, src_dir: Path, config: dict):
        pass  # rootfs 无 configure 步骤

    def compile(self, src_dir: Path, config: dict):
        self._work_dir = Path(tempfile.mkdtemp(prefix="flange-rootfs-"))
        rootfs_dir = self._work_dir / "rootfs"
        rootfs_dir.mkdir()

        # 检查 base 阶段缓存
        base_cache_path = self._get_base_cache_path(config)
        if base_cache_path and base_cache_path.exists():
            self._status("Phase 1: base 缓存命中")
            self._extract_base(base_cache_path, rootfs_dir)
        else:
            self._status("Phase 1: base 缓存未命中，完整构建")
            self._build_phase1(rootfs_dir, config)
            if base_cache_path:
                self._save_base_snapshot(rootfs_dir, base_cache_path)

        # Phase 2: Customize（总是执行）
        if self.output:
            self.output.spinner_start("Phase 2: customize...")
        self._build_phase2(rootfs_dir, config)
        if self.output:
            self.output.spinner_stop()
        self._status("Phase 2: 完成")

        # Phase 3: 压缩
        self._output = self._work_dir / "rootfs.tar.gz"
        if self.output:
            self.output.spinner_start("压缩 rootfs...")
        self.docker.run_privileged(
            ["tar", "-czf", str(self._output), "-C", str(rootfs_dir), "."])
        if self.output:
            self.output.spinner_stop()
        self._status("压缩完成")

    def _get_base_cache_path(self, config: dict) -> Path | None:
        """获取 base.tar.gz 快照路径。需要 cache 引用（由 engine 注入）。"""
        if not self.cache:
            return None
        base_hash = self.cache.compute_phase_hash("rootfs", "base")
        board = config["board"]
        # 存储在 target/<board>/.cache/，跨 product/variant 共享
        return self.cache.target_dir.parent.parent.parent / ".cache" / f"rootfs-base-{base_hash}.tar.gz"

    def _build_phase1(self, rootfs_dir: Path, config: dict):
        """Phase 1: Base rootfs — 解压 tarball + chroot apt install。"""
        tarball_path = self.source.ensure_rootfs_tarball(config)
        self.docker.run_privileged(
            ["tar", "xf", str(tarball_path), "-C", str(rootfs_dir)])
        self.docker.run_privileged(
            ["cp", "/usr/bin/qemu-aarch64-static",
             str(rootfs_dir / "usr" / "bin" / "")])

        with ChrootContext(rootfs_dir, self.docker) as chroot:
            apt_cache = rootfs_dir / "var" / "cache" / "apt" / "archives"
            apt_cache.mkdir(parents=True, exist_ok=True)
            chroot.bind_mount("/cache/apt", apt_cache)

            chroot.run(["apt-get", "update"])
            packages = config["rootfs"].get("packages", [])
            if packages:
                chroot.run(["apt-get", "install", "-y",
                            "--no-install-recommends"] + packages)
            chroot.run(["apt-get", "clean"])

    def _build_phase2(self, rootfs_dir: Path, config: dict):
        """Phase 2: Customize — overlay 文件覆盖 + custom deb 安装。"""
        board = config["board"]
        overlay_dir = Path(f"board/{board}/overlay")
        if overlay_dir.exists() and any(overlay_dir.iterdir()):
            self.docker.run_privileged(
                ["cp", "-a", f"{overlay_dir}/.", str(rootfs_dir)])

        # 安装 custom deb 包（来自 AppBuilder 产物目录）
        product = config.get("product", "default")
        variant = config.get("variant", "release")
        target_dir = Path("target") / board / product / variant
        app_deb_dir = target_dir / "app"
        if app_deb_dir.exists():
            deb_files = sorted(app_deb_dir.glob("*.deb"))
            if deb_files:
                deb_tmp = rootfs_dir / "tmp" / "flange-debs"
                deb_tmp.mkdir(parents=True, exist_ok=True)
                for deb in deb_files:
                    shutil.copy2(deb, deb_tmp)
                with ChrootContext(rootfs_dir, self.docker) as chroot:
                    deb_list = [f"/tmp/flange-debs/{d.name}" for d in deb_files]
                    chroot.run(["dpkg", "-i"] + deb_list)
                shutil.rmtree(deb_tmp)

    def _save_base_snapshot(self, rootfs_dir: Path, cache_path: Path):
        """将 Phase 1 产物保存为 base.tar.gz 快照。"""
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._status(f"保存 base 快照到 {cache_path.name}")
        self.docker.run_privileged(
            ["tar", "-czf", str(cache_path), "-C", str(rootfs_dir), "."])

    def _extract_base(self, cache_path: Path, rootfs_dir: Path):
        """从 base.tar.gz 快照解压到 rootfs_dir。"""
        self.docker.run_privileged(
            ["tar", "xf", str(cache_path), "-C", str(rootfs_dir)])

    def collect(self, src_dir: Path, config: dict) -> dict:
        return {"rootfs": self._output}
