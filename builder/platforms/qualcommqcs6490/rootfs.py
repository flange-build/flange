"""Qualcomm QCS6490 Rootfs 构建策略。

复用 RootfsBuilder 基类的 overlay / extra_debs / extra_firmware / users 等通用能力。
与 U-Boot 平台的差异：
  - UEFI 启动，但 fstab 只挂 rootfs；ESP 由 UEFI/GRUB 在启动期读取，flange 不在
    运行时 mount /boot/efi（重刷模型不走 grub-update / kernel package post-install）；
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

    def _install_kernel_boot(self, rootfs_dir: Path, config: dict):
        """把内核 Image 与 dtb 安装到 rootfs /boot，供 GRUB(grub-with-dtb) 加载。

        GRUB 的 grub.cfg 由 boot 组件生成；此处只负责把构建产物落到 /boot：
          /boot/vmlinuz   ← kernel Image
          /boot/<dtb>.dtb ← 设备树（GRUB devicetree 指令加载）
        initrd 由后续 boot 阶段在 chroot 内 update-initramfs 生成（按需）。

        ## 构建期 fdtoverlay 合并（grub-with-dtb 平台专用）

        GRUB 不支持运行时 DT overlay。当 board 经 `packages` 启用硬件特性包并由
        `builder/packages.py` 注入 `boot.package_overlays` 时，本函数在写入 /boot/
        前先用 `fdtoverlay` 把 base dtb 与所有 package overlay `.dtbo` 合成一份
        merged dtb，**覆盖式**写到 /boot/<dtb>.dtb（与 grub.cfg `devicetree
        /boot/<dtb>.dtb` 配套）。无 overlay 时走直拷路径，与未启用本能力前字节等价。

        参见 [[build-time-dtb-overlay-merge]] 规格。
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
        if not dtb.exists():
            return

        package_overlays = (config.get("boot") or {}).get("package_overlays") or []
        if not package_overlays:
            # 无 overlay：直拷 base dtb，与本能力启用前字节等价
            self.docker.run_privileged(["cp", str(dtb), str(boot / dtb.name)])
            return

        # 合并分支：base dtb + package overlays → merged dtb
        overlay_dir = target_dir / "device-tree-overlay" / "overlays"
        missing = [name for name in package_overlays
                   if not (overlay_dir / name).is_file()]
        if missing:
            raise FileNotFoundError(
                f"fdtoverlay 缺 .dtbo: {missing}（预期在 {overlay_dir}/）。"
                "请确认 device-tree-overlay 组件已构建且包内 .dtso 已编译。"
            )

        merged = self._work_dir / dtb.name
        self._status(
            f"fdtoverlay 合并 {len(package_overlays)} 个 package overlay 到 "
            f"{dtb.name}：{', '.join(package_overlays)}"
        )
        # fdtoverlay 失败时 stderr 不被吞：docker.run 默认在非零退出码时
        # 把 stderr 含进异常信息向上抛，便于排查 base dtb 缺 __symbols__
        # 或 .dtbo __fixups__ 解析不上等场景（参见 design 决策 4）。
        self.docker.run([
            "fdtoverlay",
            "-i", str(dtb),
            "-o", str(merged),
            *[str(overlay_dir / name) for name in package_overlays],
        ], label=f"fdtoverlay {dtb.name}")

        self.docker.run_privileged(["cp", str(merged), str(boot / dtb.name)])

    def _install_fstab(self, rootfs_dir: Path):
        """UEFI 布局 fstab：只挂 rootfs。

        ⚠️ 不挂 /boot/efi：ESP 由 UEFI/GRUB 在启动期读，flange 不在运行时挂。
        实测 Q6A 4096 字节 LBA UFS 上 mkfs.vfat 默认 512-sector FAT 内核 vfat
        驱动会判 superblock 无效（`can't read superblock on /dev/sda1`，强行写
        4K-sector FAT 又不被 EDK2 UEFI 识别），且 flange 模型本就不需要运行时
        修改 ESP（重刷模型，不走 grub-update / kernel package post-install）。
        删了 ESP 行后 boot-efi.mount 不存在 → local-fs.target 干净 → systemd
        is-system-running 不 degraded。
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
