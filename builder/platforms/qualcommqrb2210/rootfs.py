"""Qualcomm QRB2210 Rootfs 构建策略。

复用 RootfsBuilder 基类的 overlay / extra_debs / extra_firmware / users 等通用能力。
与 Q6A（UEFI/GRUB）的差异：本平台走 **U-Boot extlinux**，内核 Image/dtb 由
boot.py 放入独立 boot 分区（boot.img），rootfs **不**安装内核到 /boot；fstab
同时挂载 rootfs 与 boot（LABEL），与 RK/AW extlinux 平台一致。

Phase1 沿用 Q6A 的 extra_apt_sources + CA 证书处理（本平台用 qcom-ppa 取
linux-firmware-dragonwing）。
"""

import shutil
import tempfile
from pathlib import Path

from builder.rootfs import RootfsBuilder
from builder.chroot import ChrootContext


class Qrb2210RootfsBuilder(RootfsBuilder):
    component = "rootfs"

    def build(self, config: dict) -> dict:
        self.compile(None, config)
        return self.collect(None, config)

    def configure(self, src_dir, config: dict):
        pass

    def compile(self, src_dir, config: dict):
        self._work_dir = Path(tempfile.mkdtemp(prefix="flange-rootfs-"))
        rootfs_dir = self._work_dir / "rootfs"
        rootfs_dir.mkdir()

        # Phase 1: base（ubuntu-base noble + apt 包，含 qcom-ppa 额外源）
        base_cache_path = self._get_base_cache_path(config)
        if base_cache_path and base_cache_path.exists():
            self._status("Phase 1: base 缓存命中")
            self.docker.run_privileged(
                ["tar", "xf", str(base_cache_path), "-C", str(rootfs_dir)])
        else:
            self._status("Phase 1: base 构建")
            self._build_phase1(rootfs_dir, config)
            if base_cache_path:
                base_cache_path.parent.mkdir(parents=True, exist_ok=True)
                self.docker.run_privileged(
                    ["tar", "-czf", str(base_cache_path),
                     "-C", str(rootfs_dir), "."])

        # Phase 2: customize（debs / 内核模块 / 固件 / overlay / 用户）
        self._status("Phase 2: Customize")
        self._build_phase2(rootfs_dir, config)

        # Phase 3: fstab + image（内核 Image/dtb 走 boot.py 的 boot.img，不入 rootfs）
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

    def _get_base_cache_path(self, config: dict) -> Path | None:
        if not self.cache:
            return None
        base_hash = self.cache.compute_phase_hash("rootfs", "base")
        return (self.cache.target_dir.parent.parent.parent / ".cache"
                / f"rootfs-base-{base_hash}.tar.gz")

    def _build_phase1(self, rootfs_dir: Path, config: dict):
        tarball_path = self.source.ensure_rootfs_tarball(config)
        self._status("解压 base tarball...")
        self.docker.run_privileged(["tar", "xf", str(tarball_path), "-C", str(rootfs_dir)])
        self.docker.run_privileged(
            ["cp", "/usr/bin/qemu-aarch64-static", str(rootfs_dir / "usr" / "bin" / "")])

        with ChrootContext(rootfs_dir, self.docker) as chroot:
            apt_cache = rootfs_dir / "var" / "cache" / "apt" / "archives"
            apt_cache.mkdir(parents=True, exist_ok=True)
            chroot.bind_mount("/cache/apt", apt_cache)
            # Step 1：基础源 update + 装 ca-certificates（HTTPS PPA 验证需要）
            self._status("apt-get update（基础源）...")
            chroot.run(["apt-get", "update"], label="apt-get update（基础源）...")
            if self._has_extra_apt_sources(config):
                chroot.run(["apt-get", "install", "-y", "--no-install-recommends",
                            "ca-certificates"], label="安装 ca-certificates...")
                chroot.run(["update-ca-certificates"], label="update-ca-certificates...")
                # Step 2：写入额外 APT 源（CA 证书已就绪），再次 update
                self._setup_extra_apt_sources(rootfs_dir, config)
                self._status("apt-get update（含额外源）...")
                chroot.run(["apt-get", "update"], label="apt-get update（含额外源）...")
            packages = config["rootfs"].get("packages", [])
            if packages:
                self._status(f"apt-get install ({len(packages)} 个包)...")
                chroot.run(["apt-get", "install", "-y", "--no-install-recommends"] + packages,
                           label=f"安装 {len(packages)} 个包...")
            chroot.run(["apt-get", "clean"])

    def _build_phase2(self, rootfs_dir: Path, config: dict):
        product = config.get("product", "default")
        variant = config.get("variant", "release")
        target_dir = Path(".build/target") / config["board"] / product / variant

        # flange 自定义 app 的 .deb
        app_deb_dir = target_dir / "app"
        if app_deb_dir.exists():
            deb_files = sorted(app_deb_dir.glob("*.deb"))
            if deb_files:
                self._status(f"安装 {len(deb_files)} 个 deb")
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
        self._configure_users(rootfs_dir, config)
        self._install_hostname(rootfs_dir, config)

    def _install_kernel_modules(self, rootfs_dir: Path, config: dict):
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

    def _install_fstab(self, rootfs_dir: Path):
        """extlinux 布局 fstab：只挂 rootfs。

        内核 Image/dtb/extlinux.conf 在 vendor `efi` 分区（boot.py 产 FAT boot.img），
        U-Boot sysboot 启动期读取；flange 重刷模型不在运行时挂 /boot（且该分区是
        FAT、FS label 与 GPT label 不一）。只挂 rootfs，避免 systemd degraded。
        """
        fstab = rootfs_dir / "etc" / "fstab"
        if fstab.exists():
            existing = fstab.read_text()
            if any(m in existing for m in ("LABEL=", "UUID=", "/dev/", "PARTUUID=")):
                return
        fstab.parent.mkdir(parents=True, exist_ok=True)
        fstab.write_text(
            "# <file system>  <mount point>  <type>  <options>  <dump>  <pass>\n"
            "LABEL=rootfs     /              ext4    defaults   0       1\n"
        )

    def collect(self, src_dir, config: dict) -> dict:
        return {"rootfs": self._output}
