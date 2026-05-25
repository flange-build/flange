"""Qualcomm QCS6490 Rootfs 构建策略。

复用 RootfsBuilder 基类的 overlay / extra_debs / extra_firmware / users 等通用能力。
与 U-Boot 平台的差异：
  - UEFI 启动 → fstab 用 ESP(LABEL=efi) 挂 /boot/efi，无独立 /boot ext4 分区；
  - 内核 Image/dtb 安装到 rootfs 的 /boot，供 GRUB(grub-with-dtb) 经 devicetree 加载。
编排逻辑与 allwinnera733 rootfs 同构（两阶段 + 缓存），故有意显式复制。
"""

import shutil
import tempfile
from pathlib import Path

from builder.rootfs import RootfsBuilder
from builder.chroot import ChrootContext


class Qcs6490RootfsBuilder(RootfsBuilder):
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

        # Phase 1: base（ubuntu-base noble + apt 包）
        base_cache_path = self._get_base_cache_path(config)
        if base_cache_path and base_cache_path.exists():
            self._status("Phase 1: base 缓存命中")
            self.docker.run_privileged(["tar", "xf", str(base_cache_path), "-C", str(rootfs_dir)])
        else:
            self._status("Phase 1: base 构建")
            self._build_phase1(rootfs_dir, config)
            if base_cache_path:
                base_cache_path.parent.mkdir(parents=True, exist_ok=True)
                self.docker.run_privileged(
                    ["tar", "-czf", str(base_cache_path), "-C", str(rootfs_dir), "."])

        # Phase 2: customize（debs / 内核模块 / 固件 / overlay / 用户）
        self._status("Phase 2: Customize")
        self._build_phase2(rootfs_dir, config)

        # Phase 3: 内核 + fstab + image
        self._install_kernel_boot(rootfs_dir, config)
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
        return self.cache.target_dir.parent.parent.parent / ".cache" / f"rootfs-base-{base_hash}.tar.gz"

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
            self._status("apt-get update...")
            chroot.run(["apt-get", "update"], label="apt-get update...")
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

    def _install_kernel_boot(self, rootfs_dir: Path, config: dict):
        """把内核 Image 与 dtb 安装到 rootfs /boot，供 GRUB(grub-with-dtb) 加载。

        GRUB 的 grub.cfg 由 boot 组件生成；此处只负责把构建产物落到 /boot：
          /boot/vmlinuz   ← kernel Image
          /boot/<dtb>.dtb ← 设备树（GRUB devicetree 指令加载）
        initrd 由后续 boot 阶段在 chroot 内 update-initramfs 生成（按需）。
        """
        product = config.get("product", "default")
        variant = config.get("variant", "release")
        target_dir = Path(".build/target") / config["board"] / product / variant
        boot = rootfs_dir / "boot"
        boot.mkdir(exist_ok=True)
        image = target_dir / "kernel" / "Image"
        dtb = target_dir / "kernel" / f"{config['kernel']['dtb']}.dtb"
        if image.exists():
            self.docker.run_privileged(["cp", str(image), str(boot / "vmlinuz")])
        if dtb.exists():
            self.docker.run_privileged(["cp", str(dtb), str(boot / dtb.name)])

    def _install_fstab(self, rootfs_dir: Path):
        """UEFI 布局 fstab：rootfs 在 /，ESP(LABEL=efi) 挂 /boot/efi。"""
        fstab = rootfs_dir / "etc" / "fstab"
        if fstab.exists():
            existing = fstab.read_text()
            if any(m in existing for m in ("LABEL=", "UUID=", "/dev/", "PARTUUID=")):
                return
        fstab.parent.mkdir(parents=True, exist_ok=True)
        fstab.write_text(
            "# <file system>  <mount point>  <type>  <options>        <dump>  <pass>\n"
            "LABEL=rootfs     /              ext4    defaults         0       1\n"
            "LABEL=efi        /boot/efi      vfat    umask=0077       0       2\n"
        )
        (rootfs_dir / "boot" / "efi").mkdir(parents=True, exist_ok=True)

    def collect(self, src_dir, config: dict) -> dict:
        return {"rootfs": self._output}
