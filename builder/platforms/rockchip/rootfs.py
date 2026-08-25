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
from builder.config.canonical import userspace_arch
from builder.config.validate import validate_mtd_ubi
from builder.docker import BuildError
from builder.partition.rockchip import parse_parameter_file
from builder.partition.size import parse_size, resolve_image_size
from builder.paths import PROJECT_ROOT


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

        # Phase 3: 按镜像格式生成基础 fstab/mount 约定
        self._install_fstab(rootfs_dir, config)
        self._ensure_api_mountpoints(rootfs_dir)

        # Phase 4: 从 staging 目录生成 ext4 或 UBIFS/UBI 镜像。
        image_format = config.get("rootfs", {}).get("image_format", "ext4")
        if image_format == "ubi":
            self._build_ubi(rootfs_dir, config)
        else:
            self._build_ext4(rootfs_dir, config)

    def _build_ext4(self, rootfs_dir: Path, config: dict) -> None:
        """保持既有 mke2fs 路径生成 rootfs.img。"""
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

    def _build_ubi(self, rootfs_dir: Path, config: dict) -> None:
        """用显式 NAND 几何生成 UBIFS 与 UBI volume。"""
        validate_mtd_ubi(config)
        ubi = config["rootfs"]["ubi"]
        min_io = int(ubi["min_io_size"], 0) if isinstance(
            ubi["min_io_size"], str) else int(ubi["min_io_size"])
        peb = int(ubi["peb_size"], 0) if isinstance(
            ubi["peb_size"], str) else int(ubi["peb_size"])
        subpage = int(ubi["subpage_size"], 0) if isinstance(
            ubi["subpage_size"], str) else int(ubi["subpage_size"])
        vid = int(ubi["vid_hdr_offset"], 0) if isinstance(
            ubi["vid_hdr_offset"], str) else int(ubi["vid_hdr_offset"])
        leb = int(ubi["leb_size"], 0) if isinstance(
            ubi["leb_size"], str) else int(ubi["leb_size"])
        max_leb = int(ubi["max_leb_count"], 0) if isinstance(
            ubi["max_leb_count"], str) else int(ubi["max_leb_count"])
        volume_size = parse_size(ubi["volume_size"]).bytes

        self._ensure_rootfs_fits_ubi(rootfs_dir, volume_size)
        ubifs = self._work_dir / "rootfs.ubifs"
        self._status("生成 rootfs.ubifs...")
        mkfs_command = [
            "mkfs.ubifs",
            "-r", str(rootfs_dir),
            "-o", str(ubifs),
            "-m", str(min_io),
            "-e", str(leb),
            "-c", str(max_leb),
        ]
        if ubi.get("space_fixup", False):
            # 部分 USB 刷写器会把全 0xFF NAND page 也实际编程；-F 让
            # UBIFS 首次挂载先修复空闲区，避免后续写入形成二次编程。
            mkfs_command.append("-F")
        self.docker.run(mkfs_command)
        self._ensure_file_fits(
            ubifs, volume_size, "UBIFS", "rootfs.ubi.volume_size")

        ubinize_cfg = self._work_dir / "ubinize.cfg"
        ubinize_cfg.write_text(
            "[rootfs]\n"
            "mode=ubi\n"
            f"image={ubifs}\n"
            "vol_id=0\n"
            "vol_type=dynamic\n"
            "vol_name=rootfs\n"
            f"vol_size={volume_size}\n"
        )
        self._output = self._work_dir / "rootfs.ubi"
        self._status("生成 rootfs.ubi...")
        self.docker.run([
            "ubinize",
            "-o", str(self._output),
            "-m", str(min_io),
            "-p", str(peb),
            "-s", str(subpage),
            "-O", str(vid),
            str(ubinize_cfg),
        ])
        physical_limit = self._ubi_physical_limit(config, peb)
        self._ensure_file_fits(
            self._output, physical_limit, "UBI", "rootfs MTD 可用容量")

    def _ensure_rootfs_fits_ubi(
        self,
        rootfs_dir: Path,
        volume_size: int,
    ) -> None:
        """在 mkfs.ubifs 前以 staging apparent size 做逻辑容量门禁。"""
        result = self.docker.run(
            ["du", "-sb", str(rootfs_dir)], capture=True)
        used_bytes = int(result.stdout.split()[0])
        if used_bytes > volume_size:
            raise BuildError(
                f"rootfs staging 内容 {used_bytes} bytes 超过 UBI volume "
                f"{volume_size} bytes；请精简 rootfs 或增大 volume_size。")

    @staticmethod
    def _ensure_file_fits(
        path: Path,
        limit: int,
        label: str,
        limit_label: str,
    ) -> None:
        """拒绝截断超过逻辑/物理容量的 UBIFS/UBI 产物。"""
        if not path.is_file():
            raise FileNotFoundError(f"{label} 产物未生成: {path}")
        size = path.stat().st_size
        if size > limit:
            raise BuildError(
                f"{label} 产物 {size} bytes 超过 {limit_label} "
                f"{limit} bytes；禁止截断写入。")

    @staticmethod
    def _ubi_physical_limit(config: dict, peb_size: int) -> int:
        """返回扣除显式坏块余量后的 rootfs MTD 物理容量。"""
        partitions = config["partitions"]
        if partitions.get("format", "gpt") == "mtd":
            parameter = Path(partitions["parameter"])
            if not parameter.is_absolute():
                parameter = PROJECT_ROOT / parameter
            entries = parse_parameter_file(parameter)
            rootfs = next(entry for entry in entries if entry.name == "rootfs")
            storage_bytes = parse_size(config["storage"]["size"]).bytes
            partition_bytes = rootfs.size_bytes(storage_bytes)
            assert partition_bytes is not None
        else:
            rootfs_entry = next(
                entry for entry in partitions["entries"]
                if entry["name"] == "rootfs")
            # Rockchip GPT parameter 生成器会把 remaining 展开为 image_size，
            # 因此物理门禁必须使用同一解析规则。
            partition_bytes = resolve_image_size(rootfs_entry).bytes
        reserved_value = config["rootfs"]["ubi"]["reserved_pebs"]
        reserved = int(reserved_value, 0) if isinstance(
            reserved_value, str) else int(reserved_value)
        return partition_bytes - reserved * peb_size

    def _install_fstab(self, rootfs_dir: Path, config: dict | None = None):
        """按 image format 写入 /etc/fstab。

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
                line.strip() and not line.lstrip().startswith("#")
                for line in existing.splitlines()
            )
            if has_real_mount:
                return
        fstab.parent.mkdir(parents=True, exist_ok=True)
        image_format = (config or {}).get("rootfs", {}).get(
            "image_format", "ext4")
        if image_format == "ubi":
            fstab.write_text(
                "# UBI rootfs 由 kernel bootargs 挂载；不声明 ext4 root/boot 项。\n"
            )
            return
        fstab.write_text(
            "# <file system>  <mount point>  <type>  <options>  <dump>  <pass>\n"
            "LABEL=rootfs     /              ext4    defaults   0       1\n"
            "LABEL=boot       /boot          ext4    defaults   0       2\n"
        )
        # 确保 /boot 挂载点存在
        (rootfs_dir / "boot").mkdir(exist_ok=True)

    @staticmethod
    def _ensure_api_mountpoints(rootfs_dir: Path) -> None:
        """确保 systemd 启动早期使用的 API 文件系统挂载点存在。"""
        for relative in (
            "proc",
            "sys",
            "sys/fs/cgroup",
            "dev",
            "dev/pts",
            "dev/shm",
            "run",
            "run/lock",
            "tmp",
        ):
            (rootfs_dir / relative).mkdir(parents=True, exist_ok=True)
        (rootfs_dir / "tmp").chmod(0o1777)

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
        emulator = self._rootfs_emulator(config)
        self.docker.run_privileged(
            ["cp", f"/usr/bin/{emulator}",
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

    @staticmethod
    def _rootfs_emulator(config: dict) -> str:
        """按用户态 ABI 选择 chroot emulator，允许 rootfs.emulator 覆盖。"""
        rootfs = config.get("rootfs") or {}
        explicit = rootfs.get("emulator")
        if explicit:
            return explicit
        arch = userspace_arch(config)
        mapping = {
            "aarch64": "qemu-aarch64-static",
            "armhf": "qemu-arm-static",
        }
        try:
            return mapping[arch]
        except KeyError as exc:
            raise ValueError(
                f"未定义 arch={arch!r} 的 rootfs chroot emulator；"
                "请声明 rootfs.emulator") from exc

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
        self._install_panel_firmware(rootfs_dir, config)
        self.apply_overlays(rootfs_dir, config)

        # 用户 / sudo / root 账号一体化配置（基类实现，跨平台共享）
        self._configure_users(rootfs_dir, config)
        # /etc/hostname + /etc/hosts，治 sudo 解析告警（基类，跨平台共享）
        self._install_hostname(rootfs_dir, config)


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
        if config.get("rootfs", {}).get("image_format", "ext4") == "ubi":
            return {"ubi": self._output}
        return {"rootfs": self._output}
