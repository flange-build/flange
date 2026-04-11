"""Rockchip Rootfs 构建策略 -- 替代 build_base.sh + build_customize.sh"""

import shutil
import tempfile
from pathlib import Path
from builder.base import ComponentBuilder
from builder.chroot import ChrootContext


class RockchipRootfsBuilder(ComponentBuilder):
    component = "rootfs"

    def configure(self, src_dir: Path, config: dict):
        pass  # rootfs 无 configure 步骤

    def compile(self, src_dir: Path, config: dict):
        self._work_dir = Path(tempfile.mkdtemp(prefix="flange-rootfs-"))
        rootfs_dir = self._work_dir / "rootfs"
        rootfs_dir.mkdir()

        tarball_path = self.source.ensure_rootfs_tarball(config)

        # Phase 1: Base rootfs（解压 + chroot apt install）
        self.docker.run_privileged(
            ["tar", "xf", str(tarball_path), "-C", str(rootfs_dir)])
        self.docker.run_privileged(
            ["cp", "/usr/bin/qemu-aarch64-static",
             str(rootfs_dir / "usr" / "bin" / "")])

        with ChrootContext(rootfs_dir, self.docker) as chroot:
            # 挂载 APT 缓存
            apt_cache = rootfs_dir / "var" / "cache" / "apt" / "archives"
            apt_cache.mkdir(parents=True, exist_ok=True)
            chroot.bind_mount("/cache/apt", apt_cache)

            chroot.run(["apt-get", "update"])
            packages = config["rootfs"].get("packages", [])
            if packages:
                chroot.run(["apt-get", "install", "-y",
                            "--no-install-recommends"] + packages)
            chroot.run(["apt-get", "clean"])

        # Phase 2: Customize（overlay + custom debs）
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
                # 复制 .deb 到 rootfs 临时目录，避免 chroot 内路径不可见
                deb_tmp = rootfs_dir / "tmp" / "flange-debs"
                deb_tmp.mkdir(parents=True, exist_ok=True)
                for deb in deb_files:
                    shutil.copy2(deb, deb_tmp)
                # 在 chroot 环境内执行 dpkg -i 安装所有包
                with ChrootContext(rootfs_dir, self.docker) as chroot:
                    deb_list = [f"/tmp/flange-debs/{d.name}" for d in deb_files]
                    chroot.run(["dpkg", "-i"] + deb_list)
                # 清理临时目录，不保留在 rootfs 中
                shutil.rmtree(deb_tmp)

        # Phase 3: 压缩
        self._output = self._work_dir / "rootfs.tar.gz"
        self.docker.run_privileged(
            ["tar", "-czf", str(self._output), "-C", str(rootfs_dir), "."])

    def collect(self, src_dir: Path, config: dict) -> dict:
        return {"rootfs": self._output}
