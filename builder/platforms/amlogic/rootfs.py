"""Amlogic Rootfs 构建策略。

复用 RootfsBuilder 基类的两阶段缓存（base / customize）、overlay、
firmware 等通用能力。Amlogic VIM3L 的特殊性集中在 rootfs.+packages
（``firmware-brcm80211`` 提供 WiFi/BT 通用固件）与 rootfs.+extra_firmware
（fenix AP6398S 板级 NVRAM + BT patchram 覆盖），这些字段由 board config
注入，rootfs builder 自身不感知 board 差异。

与 Rockchip 同形：fstab 用 ``LABEL=`` 挂载，boot 分区有 ext4 ``LABEL=boot``。
首版无 GPU firmware 部署需求（panthor mali_csffw.bin 是 Non-Goal）。
"""

import shutil
import tempfile
from pathlib import Path
from builder.rootfs import RootfsBuilder
from builder.chroot import ChrootContext
from builder.paths import BUILD_ROOT


class AmlogicRootfsBuilder(RootfsBuilder):
    component = "rootfs"

    def build(self, config: dict) -> dict:
        """rootfs 无需克隆源码仓库。"""
        self.compile(None, config)
        return self.collect(None, config)

    def configure(self, src_dir: Path, config: dict):
        pass

    def compile(self, src_dir: Path, config: dict):
        self._work_dir = Path(tempfile.mkdtemp(prefix="flange-rootfs-"))
        rootfs_dir = self._work_dir / "rootfs"
        rootfs_dir.mkdir()

        # Phase 1: Base（按 rootfs.url + rootfs.packages 缓存 base 快照）
        base_cache_path = self._get_base_cache_path(config)
        if base_cache_path and base_cache_path.exists():
            self._status("Phase 1: base 缓存命中")
            self._extract_base(base_cache_path, rootfs_dir)
        else:
            self._status("Phase 1: base 构建")
            if self.output:
                self.output.indent()
            self._build_phase1(rootfs_dir, config)
            if base_cache_path:
                self._save_base_snapshot(rootfs_dir, base_cache_path)
            if self.output:
                self.output.dedent()

        # Phase 2: Customize（每次都跑：deb / extra_firmware / overlay / users）
        self._status("Phase 2: Customize")
        if self.output:
            self.output.indent()
        self._build_phase2(rootfs_dir, config)
        if self.output:
            self.output.dedent()

        # Phase 3: fstab + 挂载点
        self._install_fstab(rootfs_dir)

        # Phase 4: mke2fs -d 直接从目录生成 ext4 镜像（免 mount）
        self._output = self._work_dir / "rootfs.img"
        rootfs_size_mb = self._partition_size_mb(config, "rootfs")
        self._ensure_rootfs_fits_image(rootfs_dir, rootfs_size_mb)
        self._status(f"生成 rootfs.img ({rootfs_size_mb}MB)...")
        self.docker.run([
            "truncate", "-s", f"{rootfs_size_mb}M", str(self._output),
        ])
        self.docker.run([
            "mke2fs", "-t", "ext4", "-L", "rootfs", "-F", "-q",
            "-d", str(rootfs_dir), str(self._output),
        ])

    def _install_fstab(self, rootfs_dir: Path):
        """写入 /etc/fstab，挂载 rootfs 与 boot 分区。

        使用 LABEL 而非 PARTUUID，不依赖 GPT 分区表正确性。若 overlay
        已声明真实 fstab（含 LABEL= / UUID= / /dev/ / PARTUUID= 任一标记）
        则不覆盖；ubuntu-base 自带占位 fstab（仅注释）会被替换。
        """
        fstab = rootfs_dir / "etc" / "fstab"
        if fstab.exists():
            existing = fstab.read_text()
            has_real_mount = any(
                marker in existing
                for marker in ("LABEL=", "UUID=", "/dev/", "PARTUUID=")
            )
            if has_real_mount:
                return
        fstab.parent.mkdir(parents=True, exist_ok=True)
        fstab.write_text(
            "# <file system>  <mount point>  <type>  <options>  <dump>  <pass>\n"
            "LABEL=rootfs     /              ext4    defaults   0       1\n"
            "LABEL=boot       /boot          ext4    defaults   0       2\n"
        )
        (rootfs_dir / "boot").mkdir(exist_ok=True)

    def _get_base_cache_path(self, config: dict) -> Path | None:
        """获取 base.tar.gz 快照路径。需要 cache 引用（由 engine 注入）。"""
        if not self.cache:
            return None
        base_hash = self.cache.compute_phase_hash("rootfs", "base")
        # 存储在 target/<board>/.cache/，跨 product/variant 共享
        return self.cache.target_dir.parent.parent.parent / ".cache" / f"rootfs-base-{base_hash}.tar.gz"

    def _build_phase1(self, rootfs_dir: Path, config: dict):
        """Phase 1: Base rootfs — 解压 tarball + chroot apt install。"""
        tarball_path = self.source.ensure_rootfs_tarball(config)
        self._status("解压 base tarball...")
        self.docker.run_privileged(
            ["tar", "xf", str(tarball_path), "-C", str(rootfs_dir)])
        self.docker.run_privileged(
            ["cp", "/usr/bin/qemu-aarch64-static",
             str(rootfs_dir / "usr" / "bin" / "")])

        with ChrootContext(rootfs_dir, self.docker) as chroot:
            apt_cache = rootfs_dir / "var" / "cache" / "apt" / "archives"
            apt_cache.mkdir(parents=True, exist_ok=True)
            chroot.bind_mount("/cache/apt", apt_cache)

            self._status("apt-get update...")
            chroot.run(["apt-get", "update"], label="apt-get update...")
            packages = config["rootfs"].get("packages", [])
            if packages:
                self._status(f"apt-get install ({len(packages)} 个包)...")
                chroot.run(["apt-get", "install", "-y",
                            "--no-install-recommends"] + packages,
                           label=f"安装 {len(packages)} 个包...")
            chroot.run(["apt-get", "clean"])

    def _build_phase2(self, rootfs_dir: Path, config: dict):
        """Phase 2: Customize — app deb + extra deb/firmware + overlay + users。"""
        product = config.get("product", "default")
        variant = config.get("variant", "release")
        # 用 BUILD_ROOT 锚点（绝对路径），避免 cwd 依赖（ProjectSpec §9）。
        target_dir = BUILD_ROOT / "target" / config["board"] / product / variant
        app_deb_dir = target_dir / "app"
        if app_deb_dir.exists():
            deb_files = sorted(app_deb_dir.glob("*.deb"))
            if deb_files:
                deb_names = [d.name for d in deb_files]
                self._status(f"安装 {len(deb_files)} 个 deb: {', '.join(deb_names)}")
                deb_tmp = rootfs_dir / "tmp" / "flange-debs"
                deb_tmp.mkdir(parents=True, exist_ok=True)
                for deb in deb_files:
                    shutil.copy2(deb, deb_tmp)
                with ChrootContext(rootfs_dir, self.docker) as chroot:
                    deb_list = [f"/tmp/flange-debs/{d.name}" for d in deb_files]
                    chroot.run(["dpkg", "-i", "--force-confnew"] + deb_list,
                               label=f"dpkg -i ({len(deb_files)} 个包)...")
                shutil.rmtree(deb_tmp)

        self._install_extra_debs(rootfs_dir, config)
        self._install_kernel_modules(rootfs_dir, config)
        self._install_extra_firmware(rootfs_dir, config)
        self._install_panel_firmware(rootfs_dir, config)
        self.apply_overlays(rootfs_dir, config)

        # 用户 / sudo / root 账号一体化配置（基类实现，跨平台共享）
        self._configure_users(rootfs_dir, config)

    def _install_kernel_modules(self, rootfs_dir: Path, config: dict):
        """将 kernel 产物中的 modules 安装到 rootfs /lib/modules/。

        kernel 构建后，engine 将 _modules_staging 复制到
        ``target/<board>/<product>/<variant>/kernel/modules/``，
        其内部结构为 ``lib/modules/<version>/...``；这里把 ``lib/modules/``
        子树整体复制进 rootfs。
        """
        product = config.get("product", "default")
        variant = config.get("variant", "release")
        # 用 BUILD_ROOT 锚点（绝对路径），避免 cwd 依赖（ProjectSpec §9）。
        target_dir = BUILD_ROOT / "target" / config["board"] / product / variant
        modules_src = target_dir / "kernel" / "modules" / "lib" / "modules"
        if not modules_src.is_dir():
            return
        self._status("安装内核模块...")
        dest = rootfs_dir / "lib" / "modules"
        dest.mkdir(parents=True, exist_ok=True)
        self.docker.run_privileged(
            ["cp", "-a", f"{modules_src}/.", str(dest)])

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
