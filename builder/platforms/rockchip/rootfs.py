"""Rockchip Rootfs 构建策略 -- 替代 build_base.sh + build_customize.sh

支持两阶段独立缓存：
- Phase 1 (Base): 解压 tarball + apt install → 缓存为 base.tar.gz 快照
- Phase 2 (Customize): overlay + custom debs → 最终 rootfs.tar.gz
"""

import shutil
import tempfile
from pathlib import Path
from builder.rootfs import RootfsBuilder
from builder.chroot import ChrootContext


class RockchipRootfsBuilder(RootfsBuilder):
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
            self._status("Phase 1: base 构建")
            if self.output:
                self.output.indent()
            self._build_phase1(rootfs_dir, config)
            if base_cache_path:
                self._save_base_snapshot(rootfs_dir, base_cache_path)
            if self.output:
                self.output.dedent()

        # Phase 2: Customize（总是执行）
        self._status("Phase 2: Customize")
        if self.output:
            self.output.indent()
        self._build_phase2(rootfs_dir, config)
        if self.output:
            self.output.dedent()

        # Phase 3: 确保基础 /etc/fstab 和挂载点存在
        self._install_fstab(rootfs_dir)

        # Phase 4: 从目录生成 ext4 rootfs.img（免 mount，mke2fs -d 直读目录）
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
        """写入 /etc/fstab，挂载 rootfs 和 boot 分区。

        使用 LABEL 而非 PARTUUID，不依赖 GPT 分区表正确性。
        若 overlay 已提供真实 /etc/fstab（声明 LABEL= / UUID= / /dev/ /
        PARTUUID= 任一挂载项），则尊重 overlay 版本不覆盖。

        ubuntu-base tarball 自带的占位 fstab 仅含 "# UNCONFIGURED FSTAB FOR
        BASE SYSTEM" 注释、无任何挂载项，会通过 ".strip() 非空" 判断逃逸；
        必须显式按"是否含挂载项标记"来判断。
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
        # 确保 /boot 挂载点存在
        (rootfs_dir / "boot").mkdir(exist_ok=True)

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
        """Phase 2: Customize — custom deb 安装 + overlay 文件覆盖。"""
        # 先安装 deb，再安装额外固件，最后覆盖 overlay（overlay 优先级最高）
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

        # 设置 root 密码（若 config 中声明）
        root_password = config.get("rootfs", {}).get("root_password")
        if root_password:
            self._set_root_password(rootfs_dir, root_password)


    def _install_kernel_modules(self, rootfs_dir: Path, config: dict):
        """将 kernel 组件产物目录中的模块安装到 rootfs /lib/modules/。

        kernel 构建后，engine 将 _modules_staging 复制到
        target/<board>/<product>/<variant>/kernel/modules/，
        其内部结构为 lib/modules/<version>/...
        这里把 lib/modules/ 子树整体复制进 rootfs。
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
        self.docker.run_privileged(
            ["cp", "-a", f"{modules_src}/.", str(dest)])

    def _set_root_password(self, rootfs_dir: Path, password: str):
        """设置 root 账号密码，精确匹配旧 Bazel 方案：

            echo "root:<password>" | chroot <rootfs> chpasswd

        chpasswd 在 chroot 内执行（通过 qemu-user-static 模拟 arm64），
        读 stdin 的 user:password 行写入 /etc/shadow。

        使用 ChrootContext 确保 /proc /sys /dev 已挂载：chpasswd 通过
        libcrypt 生成盐值时可能读 /dev/urandom，缺失时会静默失败或
        产生无效哈希。

        执行后立即读 /etc/shadow 硬校验 root 行：若密码字段仍是
        锁定态（!/*/空）或格式非法，抛错而非静默产生不可登录镜像。
        """
        self._status("设置 root 密码...")
        with ChrootContext(rootfs_dir, self.docker) as chroot:
            chroot.run(["chpasswd"], input=f"root:{password}\n")
        self._verify_root_password(rootfs_dir)

    def _verify_root_password(self, rootfs_dir: Path):
        """校验 /etc/shadow 中 root 行密码字段已被正确设置。"""
        shadow = rootfs_dir / "etc" / "shadow"
        if not shadow.exists():
            raise RuntimeError(f"/etc/shadow 不存在: {shadow}")
        for line in shadow.read_text().splitlines():
            if not line.startswith("root:"):
                continue
            fields = line.split(":")
            if len(fields) < 2:
                raise RuntimeError(
                    f"/etc/shadow root 行格式错误: {line!r}")
            pw_hash = fields[1]
            if pw_hash in ("", "!", "*", "!!", "x"):
                raise RuntimeError(
                    f"root 密码未生效：/etc/shadow 字段仍为 {pw_hash!r}，"
                    f"chpasswd 未成功写入（检查 chroot/qemu 环境）")
            if not pw_hash.startswith("$"):
                raise RuntimeError(
                    f"root 密码哈希格式非预期: {pw_hash[:40]!r}")
            self._status(f"root 密码已写入 (hash: {pw_hash[:12]}...)")
            return
        raise RuntimeError("/etc/shadow 中未找到 root 账号行")

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
