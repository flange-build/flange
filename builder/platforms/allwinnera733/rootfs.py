"""Allwinner A733 Rootfs 构建策略。

复用 RootfsBuilder 基类的两阶段缓存、overlay、firmware 等通用能力，
与 Rockchip 版本的主要差异在于 fstab 中 root 分区的定位方式。
"""

import shutil
import tempfile
from pathlib import Path
from builder.rootfs import RootfsBuilder
from builder.chroot import ChrootContext


class AllwinnerA733RootfsBuilder(RootfsBuilder):
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

        # Phase 1: Base
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

        # Phase 2: Customize
        self._status("Phase 2: Customize")
        if self.output:
            self.output.indent()
        self._build_phase2(rootfs_dir, config)
        if self.output:
            self.output.dedent()

        # Phase 3: fstab + image
        self._install_fstab(rootfs_dir)

        rootfs_size_mb = self._partition_size_mb(config, "rootfs")
        self._output = self._work_dir / "rootfs.img"
        self._ensure_rootfs_fits_image(rootfs_dir, rootfs_size_mb)
        self._status(f"生成 rootfs.img ({rootfs_size_mb}MB)...")
        self.docker.run(["truncate", "-s", f"{rootfs_size_mb}M", str(self._output)])
        self.docker.run([
            "mke2fs", "-t", "ext4", "-L", "rootfs", "-F", "-q",
            "-d", str(rootfs_dir), str(self._output),
        ])

    def _install_fstab(self, rootfs_dir: Path):
        """写入 /etc/fstab。使用 LABEL 挂载。

        ubuntu-base tarball 自带占位 fstab 仅含注释、无挂载项；判断"是否
        被 overlay 自定义"必须按是否含 LABEL= / UUID= / /dev/ / PARTUUID=
        任一挂载项标记，而非简单的 ".strip() 非空"。
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
        if not self.cache:
            return None
        base_hash = self.cache.compute_phase_hash("rootfs", "base")
        return self.cache.target_dir.parent.parent.parent / ".cache" / f"rootfs-base-{base_hash}.tar.gz"

    def _build_phase1(self, rootfs_dir: Path, config: dict):
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
        product = config.get("product", "default")
        variant = config.get("variant", "release")
        target_dir = Path(".build/target") / config["board"] / product / variant
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
        self.apply_overlays(rootfs_dir, config)

        root_password = config.get("rootfs", {}).get("root_password")
        if root_password:
            self._set_root_password(rootfs_dir, root_password)

    def _install_kernel_modules(self, rootfs_dir: Path, config: dict):
        """安装 kernel modules_install 产物到 rootfs 的 /lib/modules。

        kernel 构建阶段通过 modules_install 产出标准 lib/modules 树；
        rootfs 依赖 kernel 后，只需保持该目录结构原样复制，modprobe 才能
        正确读取 modules.dep、modules.alias 等索引文件。
        """
        product = config.get("product", "default")
        variant = config.get("variant", "release")
        target_dir = Path(".build/target") / config["board"] / product / variant
        modules_src = target_dir / "kernel" / "modules" / "lib" / "modules"
        if not modules_src.is_dir():
            return
        self._status("安装内核模块...")
        dest = rootfs_dir / "lib" / "modules"
        dest.mkdir(parents=True, exist_ok=True)
        self.docker.run_privileged(["cp", "-a", f"{modules_src}/.", str(dest)])

    def _set_root_password(self, rootfs_dir: Path, password: str):
        self._status("设置 root 密码...")
        with ChrootContext(rootfs_dir, self.docker) as chroot:
            chroot.run(["chpasswd"], input=f"root:{password}\n")
        self._verify_root_password(rootfs_dir)

    def _verify_root_password(self, rootfs_dir: Path):
        shadow = rootfs_dir / "etc" / "shadow"
        if not shadow.exists():
            raise RuntimeError(f"/etc/shadow 不存在: {shadow}")
        for line in shadow.read_text().splitlines():
            if not line.startswith("root:"):
                continue
            fields = line.split(":")
            if len(fields) < 2:
                raise RuntimeError(f"/etc/shadow root 行格式错误: {line!r}")
            pw_hash = fields[1]
            if pw_hash in ("", "!", "*", "!!", "x"):
                raise RuntimeError(
                    f"root 密码未生效：/etc/shadow 字段仍为 {pw_hash!r}")
            if not pw_hash.startswith("$"):
                raise RuntimeError(f"root 密码哈希格式非预期: {pw_hash[:40]!r}")
            self._status(f"root 密码已写入 (hash: {pw_hash[:12]}...)")
            return
        raise RuntimeError("/etc/shadow 中未找到 root 账号行")

    def _save_base_snapshot(self, rootfs_dir: Path, cache_path: Path):
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._status(f"保存 base 快照到 {cache_path.name}")
        self.docker.run_privileged(
            ["tar", "-czf", str(cache_path), "-C", str(rootfs_dir), "."])

    def _extract_base(self, cache_path: Path, rootfs_dir: Path):
        self.docker.run_privileged(
            ["tar", "xf", str(cache_path), "-C", str(rootfs_dir)])

    def collect(self, src_dir: Path, config: dict) -> dict:
        return {"rootfs": self._output}
