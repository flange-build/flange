"""RootfsBuilder — 各平台 rootfs 构建器的公共基类。

通用能力（与平台无关）：
  - apply_overlays：platform overlay → board overlay 两层覆盖
  - extra_apt_sources：写入外部 APT 源和 GPG key，供 Phase 1 apt-get update 前使用
  - extra_debs：下载第三方 deb 并安装
  - extra_firmware：从外部仓库拉取固件文件并写入 rootfs
  - panel_firmware：把板级 panel init 文本源编译为 panel.bin 写入 rootfs
  - configure_default_locale：写入系统默认 locale
  - configure_users：创建 group / 普通用户 / sudo 配置 / root 密码 /
                     disable_root_login（含 chroot 内 chpasswd / passwd -l /
                     /etc/sudoers.d 写入 / sshd_config drop-in 写入）、默认
                     图形会话，并为 desktop 生成 GNOME Remote Login
                     首启凭据
"""

import json
import math
import shutil
from pathlib import Path
from builder.base import ComponentBuilder
from builder.chroot import ChrootContext
from builder.docker import BuildError
from builder.firmware_panel import encode_file as _encode_panel_file
from builder.partition.layout import PartitionLayout
from builder.snapshot import SnapshotStore
from builder.rootfs_storage import rootfs_staging
from builder.rootfs_base import (
    base_plan,
    build_base,
    emulator_for,
    apt_command,
    install_extra_sources,
)


# 写入 /etc/sudoers.d/ 时统一使用 0440，与 visudo 默认权限和 sudo 自身的
# 严格性检查一致；权限错则 sudo 直接拒绝读该文件，提权静默失败。
_SUDOERS_D_MODE = 0o440


class RootfsBuilder(ComponentBuilder):
    """rootfs 构建器基类。

    各平台子类继承此类，获得通用 rootfs 能力，再叠加平台特定逻辑。
    """

    component = "rootfs"

    # ------------------------------------------------------------------
    # 四相编排：base 快照 → customize → fstab → 成像
    #
    # 这份编排此前在 4 个平台 + recovery 里手抄了 5 份，AST 归一化对比显示
    # 42% 是冗余且 8 组同名函数中 6 组已漂移 —— 漂移的代价不是重复，而是
    # 基类新增的能力接不上抄件（rootfs.emulator、extra_apt_sources 等在
    # 多数平台上是静默 no-op）。平台差异一律走下面这几个声明位，不要再复制
    # 整段 compile。
    # ------------------------------------------------------------------

    #: fstab 挂载项 (spec, mount point, fstype)。用 LABEL 而非 PARTUUID，
    #: 不依赖 GPT 分区表正确性。空元组表示"这个 rootfs 不由 fstab 挂载"
    #: （如 UBI 由 kernel bootargs 挂 root）。
    FSTAB_MOUNTS: tuple[tuple[str, str, str], ...] = (
        ("LABEL=rootfs", "/", "ext4"),
        ("LABEL=boot", "/boot", "ext4"),
    )

    #: 平台/板级 overlay 的目录名。recovery 用 ``recovery-overlay`` 与
    #: normal rootfs 的 overlay 分开，这样同一块板可以给两者不同的配置。
    OVERLAY_SUBDIR = "overlay"

    def build(self, config: dict) -> dict:
        """rootfs 无源码仓库，跳过 source.ensure / reset / patch。"""
        self.compile(None, config)
        return self.collect(None, config)

    def configure(self, src_dir: Path, config: dict):
        pass  # rootfs 无 configure 步骤

    def compile(self, src_dir: Path, config: dict):
        self._work_dir = self.work_dir()
        with rootfs_staging(self.component) as rootfs_dir:
            self._compile_rootfs(rootfs_dir, config)

    def _compile_rootfs(self, rootfs_dir: Path, config: dict) -> None:
        """完整可变文件树生命周期在同一原生存储中执行。"""

        # Phase 1：解压 base tarball + apt install。切口选在"apt 不做增量"
        # 这个真实的工具边界上，产物按内容哈希缓存、跨 target 共享。
        base_cache_path = self._get_base_cache_path(config)
        if base_cache_path and self._extract_base(base_cache_path, rootfs_dir):
            self._status("Phase 1: base 缓存命中")
        else:
            self._status("Phase 1: base 构建")
            if self.output:
                self.output.indent()
            self._build_phase1(rootfs_dir, config)
            if base_cache_path:
                self._save_base_snapshot(rootfs_dir, base_cache_path)
            if self.output:
                self.output.dedent()

        # Phase 2：每次都跑。步骤间有两条顺序硬约束——board overlay 必须在
        # app deb 之后（overlay 要压回 deb 里的 conffile），rootfs overlay
        # 必须在 useradd -m 之前（useradd 从 /etc/skel 拷贝）。
        self._status("Phase 2: Customize")
        if self.output:
            self.output.indent()
        self._build_phase2(rootfs_dir, config)
        if self.output:
            self.output.dedent()

        self._post_customize(rootfs_dir, config)

        # Phase 3：挂载约定
        self._install_fstab(rootfs_dir, config)
        self._ensure_api_mountpoints(rootfs_dir)

        # Phase 4：成像
        self._build_image(rootfs_dir, config)

    def collect(self, src_dir: Path, config: dict) -> dict:
        outputs = {self.component: self._output}
        if getattr(self, "_packages_manifest", None):
            outputs["packages"] = self._packages_manifest
        return outputs

    def _post_customize(self, rootfs_dir: Path, config: dict) -> None:
        """Phase 2 之后、写 fstab 之前的平台钩子。默认无操作。"""

    def _build_image(self, rootfs_dir: Path, config: dict) -> None:
        """从 staging 目录生成镜像。默认 ext4；UBI 等路由由平台覆写。"""
        image_name = f"{self.component}.img"
        self._output = self._work_dir / image_name
        size_mb = self._partition_size_mb(config, self.component)
        self._ensure_rootfs_fits_image(rootfs_dir, size_mb)
        self._status(f"生成 {image_name} ({size_mb}MB)...")
        self.docker.run(["truncate", "-s", f"{size_mb}M", str(self._output)])
        self.docker.run(
            [
                "mke2fs",
                "-t",
                "ext4",
                "-L",
                self.component,
                "-F",
                "-q",
                "-d",
                str(rootfs_dir),
                str(self._output),
            ]
        )

    def _build_phase1(self, rootfs_dir: Path, config: dict) -> None:
        """执行用于查询快照的同一份 Phase 1 计划。"""
        plan = self._phase1_plan
        before = plan.fingerprint()
        build_base(
            plan,
            rootfs_dir,
            context=self.context,
            source=self.source,
            docker=self.docker,
            status=self._status,
        )
        if plan.fingerprint() != before:
            raise BuildError("base 构建期间输入变化，拒绝保存快照")

    def _build_phase2(self, rootfs_dir: Path, config: dict) -> None:
        """custom deb → extra deb → 模块 → 固件 → overlay → locale → 账号。"""
        self._install_app_debs(rootfs_dir, config)
        self._install_extra_debs(rootfs_dir, config)
        self._install_kernel_modules(rootfs_dir, config)
        self._install_extra_firmware(rootfs_dir, config)
        self._install_panel_firmware(rootfs_dir, config)
        self.apply_overlays(rootfs_dir, config)
        self._configure_default_locale(rootfs_dir, config)
        self._configure_users(rootfs_dir, config)
        self._install_hostname(rootfs_dir, config)
        self._export_package_manifest(rootfs_dir)

    def _export_package_manifest(self, rootfs_dir: Path) -> None:
        """导出镜像内已安装包的名称与版本清单。

        今天只有 ubuntu-base tarball 被 sha256 钉住，之后装进去的数百个 apt
        包一个版本都没钉：同一个 git commit 隔一个月构建，镜像内容不同，而
        `flange build` 报"无变更、跳过" —— 缓存在这里主动说谎。

        钉版本会让开发期跟随上游修复变得困难（apt 会因上游删除旧版本而解析
        失败），所以先只做**事后可审计**：清单同时写进镜像（现场排查用）与
        产物目录（不刷机也能 diff 两次构建的差异）。
        """
        manifest = rootfs_dir / "etc" / "flange" / "packages.manifest"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        self._status("导出已安装包清单...")
        with ChrootContext(rootfs_dir, self.docker) as chroot:
            chroot.run(
                [
                    "/bin/sh",
                    "-c",
                    "dpkg-query -W -f='${binary:Package}\t${Version}\n' "
                    "| sort > /etc/flange/packages.manifest",
                ],
                label="dpkg-query 导出包清单...",
            )
        if manifest.is_file():
            self._packages_manifest = self._work_dir / "packages.manifest"
            shutil.copy2(manifest, self._packages_manifest)

    def _target_dir(self) -> Path:
        """依赖产物严格来自当前显式目标。"""
        if self.context is None:
            raise RuntimeError("rootfs 构建必须注入 WorkspaceContext")
        return self.context.target_dir

    def _install_app_debs(self, rootfs_dir: Path, config: dict) -> None:
        """只安装本次报告中请求 App 的完整运行依赖闭包。"""
        names = self._component_config(config).get("custom_packages") or []
        if self.app_report is None:
            raise BuildError("rootfs 缺少本次构建的 AppBuildReport")
        if not self.app_report.validate():
            raise BuildError("App 产物已经变更或缺失，拒绝安装")
        packages = self.app_report.runtime_packages_for(names)
        if any(package.format != "deb" for package in packages):
            raise BuildError("Ubuntu rootfs 仅支持安装 DEB 格式的 App 包")
        deb_files = tuple(package.path for package in packages)
        if not deb_files:
            return
        names = [deb.name for deb in deb_files]
        self._status(f"安装 {len(deb_files)} 个 deb: {', '.join(names)}")
        deb_tmp = rootfs_dir / "tmp" / "flange-debs"
        deb_tmp.mkdir(parents=True, exist_ok=True)
        for deb in deb_files:
            shutil.copy2(deb, deb_tmp)
        with ChrootContext(rootfs_dir, self.docker) as chroot:
            chroot.run(
                ["dpkg", "-i", "--force-confnew"]
                + [f"/tmp/flange-debs/{deb.name}" for deb in deb_files],
                label=f"dpkg -i ({len(deb_files)} 个包)...",
            )
        shutil.rmtree(deb_tmp)

    def _install_kernel_modules(self, rootfs_dir: Path, config: dict) -> None:
        """把 kernel 产物里的 lib/modules 子树整体复制进 rootfs。

        保持目录结构原样，modprobe 才能读到 modules.dep / modules.alias
        这些索引。
        """
        modules_root = self._target_dir() / "kernel" / "modules"
        if not modules_root.is_dir():
            raise BuildError(f"内核模块产物缺失: {modules_root}")
        modules_src = modules_root / "lib/modules"
        if not modules_src.is_dir():
            if any(modules_root.iterdir()):
                raise BuildError(f"内核模块产物目录结构不完整: {modules_root}")
            return
        self._status("安装内核模块...")
        dest = rootfs_dir / "lib" / "modules"
        dest.mkdir(parents=True, exist_ok=True)
        self.docker.run_privileged(["cp", "-a", f"{modules_src}/.", str(dest)])

    def _fstab_mounts(self, config: dict) -> tuple:
        """返回本次要写进 fstab 的挂载项。默认取类常量，可按配置路由。"""
        return self.FSTAB_MOUNTS

    def _install_fstab(self, rootfs_dir: Path, config: dict) -> None:
        """写 /etc/fstab；overlay 已声明真实 fstab 则不覆盖。

        判据是"是否含挂载项标记"而非"是否有非注释行"：ubuntu-base tarball
        自带的占位 fstab 只有一行 "# UNCONFIGURED FSTAB FOR BASE SYSTEM"
        注释、没有任何挂载项，按后者判会被误认成"overlay 已接管 fstab"。
        """
        fstab = rootfs_dir / "etc" / "fstab"
        if fstab.exists():
            existing = fstab.read_text()
            if any(marker in existing for marker in ("LABEL=", "UUID=", "/dev/", "PARTUUID=")):
                return
        fstab.parent.mkdir(parents=True, exist_ok=True)

        mounts = self._fstab_mounts(config)
        if not mounts:
            fstab.write_text("# 根文件系统不由 fstab 挂载（由 kernel bootargs 指定）。\n")
            return

        lines = ["# <file system>  <mount point>  <type>  <options>  <dump>  <pass>"]
        for index, (spec, mount, fstype) in enumerate(mounts):
            lines.append(
                f"{spec:<16} {mount:<14} {fstype:<7} defaults   0       {1 if index == 0 else 2}"
            )
        fstab.write_text("\n".join(lines) + "\n")
        for _spec, mount, _fstype in mounts:
            if mount != "/":
                (rootfs_dir / mount.lstrip("/")).mkdir(parents=True, exist_ok=True)

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

    @staticmethod
    def _rootfs_emulator(config: dict) -> str:
        """与 Phase 1 计划共用 emulator 解析。"""
        return emulator_for(config)

    # ------------------------------------------------------------------
    # Phase 1 base 快照（跨 board/product/variant 共享，四个平台共用同一套）
    # ------------------------------------------------------------------

    def _base_snapshot_store(self) -> SnapshotStore:
        """base 产物按输入寻址，在同一 build_root 的目标间共享。"""
        return SnapshotStore(
            self.context.build_root / "cache/rootfs-base",
            "base-",
            self.docker,
            status=self._status,
        )

    def _get_base_cache_path(self, config: dict) -> Path | None:
        """计划同时决定快照身份与实际执行参数。"""
        if self.context is None:
            raise RuntimeError("base 构建必须注入 WorkspaceContext")
        self._phase1_plan = base_plan(config, self.component, self.context)
        return self._base_snapshot_store().resolve(self._phase1_plan.fingerprint().digest)

    def _save_base_snapshot(self, rootfs_dir: Path, cache_path: Path):
        """把 Phase 1 产物保存为快照，并回收超额的旧快照。"""
        self._base_snapshot_store().save(rootfs_dir, cache_path)

    def _extract_base(self, cache_path: Path, rootfs_dir: Path):
        """从快照解压到 rootfs 目录。"""
        return self._base_snapshot_store().restore(cache_path, rootfs_dir)

    def apply_overlays(self, rootfs_dir: Path, config: dict):
        """按优先级顺序应用 overlay 文件：rootfs → platform → board。

        优先级从低到高，后应用的同名文件覆盖先应用的：
          components/rootfs/overlay/          与 OS/发行版绑定，所有平台共用
          components/platform/<p>/overlay/    与芯片平台绑定
          components/board/<b>/overlay/       与具体板子绑定
        """
        subdir = self.OVERLAY_SUBDIR
        for overlay_dir, label in [
            (self.components_root / self.component / "overlay", self.component),
            (self.components_root / "platform" / config["platform"] / subdir, "platform"),
            (self.components_root / "board" / config["board"] / subdir, "board"),
        ]:
            if overlay_dir.exists() and any(overlay_dir.iterdir()):
                self._status(f"复制 {label} overlay 文件...")
                self.docker.run_privileged(["cp", "-a", f"{overlay_dir}/.", str(rootfs_dir)])

    def _partition_size_mb(self, config: dict, name: str) -> int:
        """指定分区的初始镜像大小（MiB）。几何解析统一走 PartitionLayout。"""
        return PartitionLayout.from_config(config).size_mb(name)

    def _apt_install_command(self, packages: list[str], config: dict) -> list[str]:
        """与 Phase 1 执行共用命令生成。"""
        return apt_command(
            {
                "packages": packages,
                "install_recommends": self._component_config(config).get(
                    "install_recommends", False
                ),
            }
        )

    def _ensure_rootfs_fits_image(self, rootfs_dir: Path, image_size_mb: int):
        """构建 ext4 前检查 rootfs 内容是否能放入初始镜像。

        门禁只做一件事：**预测 mke2fs 会不会因空间不足失败**，好让报错说人话
        而不是抛 mke2fs 的晦涩输出。它不承担"运行期该留多少余量"的策略 ——
        那没有公认阈值，且会在能正常工作的配置上误报。

        保留量按实测的 ext4 开销定：rock5b 的 recovery 实测 du 449MB 的内容
        做进 512MiB 镜像后占 461MB，开销约 12MB（2.7%）—— 主要是 journal 与
        inode 表。取 8% 是它的约 3 倍，下限 32MiB 覆盖小镜像的固定 journal
        开销。

        这里踩过一次：初版按 rootfs 的经验取 20% 且下限固定 128MiB，直接把
        rock5b 的 recovery 拦下了（要求 577MB > 分区 512MB），而同样内容用
        旧代码构建出的镜像是有效 ext4、还剩 75MB。20% 是按 rootfs 定的，而
        rootfs 首启会 growpart 扩容、本来就不需要初始余量；recovery 是固定
        尺寸的救援分区，刻意装满才是常态。
        """
        result = self.docker.run(
            ["du", "-sm", str(rootfs_dir)],
            capture=True,
        )
        used_mb = int(result.stdout.split()[0])
        reserve_mb = max(math.ceil(used_mb * 0.08), 32)
        required_mb = used_mb + reserve_mb
        if required_mb > image_size_mb:
            raise BuildError(
                f"{self.component} 内容约 {used_mb}MB，算上 ext4 元数据开销"
                f"需要至少 {required_mb}MB；当前 image_size 仅 "
                f"{image_size_mb}MB，请增大 {self.component} 分区 image_size "
                f"或减少装入的内容。"
            )

    def _component_config(self, config: dict) -> dict:
        """本构建器负责的 config 子树：rootfs 读 `rootfs`，recovery 读 `recovery`。

        packages / custom_packages / install_recommends / extra_apt_sources
        都在这棵子树下，两者互不影响。
        """
        return config.get(self.component) or {}

    def _has_extra_apt_sources(self, config: dict) -> bool:
        return bool(self._component_config(config).get("extra_apt_sources"))

    def _setup_extra_apt_sources(self, rootfs_dir: Path, config: dict):
        """与 Phase 1 执行共用软件源设置。"""
        install_extra_sources(
            rootfs_dir,
            self._component_config(config).get("extra_apt_sources") or [],
            self.source,
            self.docker,
            self._status,
        )

    def _configure_default_locale(self, rootfs_dir: Path, config: dict) -> None:
        """按 canonical 配置写入 systemd 与 Debian 的默认 locale 路径。"""
        locale = (config.get("rootfs") or {}).get("default_locale")
        if locale is None:
            return

        content = f"LANG={locale['lang']}\nLANGUAGE={locale['language']}\n"
        self._status(f"设置默认 locale: {locale['lang']}")
        locale_conf = rootfs_dir / "etc/locale.conf"
        locale_conf.parent.mkdir(parents=True, exist_ok=True)
        locale_conf.write_text(content, encoding="utf-8")
        locale_conf.chmod(0o644)

        default_locale = rootfs_dir / "etc/default/locale"
        default_locale.parent.mkdir(parents=True, exist_ok=True)
        default_locale.unlink(missing_ok=True)
        default_locale.symlink_to("../locale.conf")

    def _install_extra_debs(self, rootfs_dir: Path, config: dict):
        """下载并安装第三方 deb 包到 rootfs。

        config["rootfs"]["extra_debs"] 格式：
          [
            {
              "name": "xserver-xorg-img-bxm",
              "url": "https://github.com/.../xserver-xorg-img-bxm_1.21.1-2_arm64.deb",
              "sha256": "<hex>",
              "filename": "xserver-xorg-img-bxm_1.21.1-2_arm64.deb",  # 可选
              "force_overwrite": true,  # 可选，允许覆盖其他包拥有的文件
              "hold_packages": ["xserver-xorg-img-bxm"],  # 可选
            },
          ]

        name 用于缓存目录隔离，必须全局唯一。deb 在 app deb 之后、
        kernel modules 之前安装，与 Phase 2 其他 deb 共享 dpkg -i 流程。
        """
        extra_debs = config.get("rootfs", {}).get("extra_debs", [])
        if not extra_debs:
            return
        deb_entries = []
        for deb_cfg in extra_debs:
            name = deb_cfg["name"]
            self._status(f"下载外部 deb: {name}")
            deb_path = self.source.ensure_extra_deb(name, deb_cfg)
            deb_entries.append((deb_cfg, deb_path))
        deb_files = [entry[1] for entry in deb_entries]
        deb_names = [d.name for d in deb_files]
        self._status(f"安装 {len(deb_files)} 个外部 deb: {', '.join(deb_names)}")
        deb_tmp = rootfs_dir / "tmp" / "flange-extra-debs"
        deb_tmp.mkdir(parents=True, exist_ok=True)
        for deb in deb_files:
            shutil.copy2(deb, deb_tmp)
        with ChrootContext(rootfs_dir, self.docker) as chroot:
            batches = []
            for deb_cfg, deb_file in deb_entries:
                force_overwrite = deb_cfg.get("force_overwrite", False)
                if not batches or batches[-1][0] != force_overwrite:
                    batches.append((force_overwrite, []))
                batches[-1][1].append(deb_file)
            for force_overwrite, batch in batches:
                command = ["dpkg", "-i", "--force-confnew"]
                if force_overwrite:
                    command.append("--force-overwrite")
                command.extend(f"/tmp/flange-extra-debs/{deb.name}" for deb in batch)
                chroot.run(
                    command,
                    label=f"dpkg -i ({len(batch)} 个外部包)...",
                )

            hold_packages = list(
                dict.fromkeys(
                    package
                    for deb_cfg, _ in deb_entries
                    for package in deb_cfg.get("hold_packages", [])
                )
            )
            if hold_packages:
                chroot.run(
                    [
                        "/bin/sh",
                        "-c",
                        "set -xe\n"
                        "for package do\n"
                        "    if dpkg-query -W -f='${db:Status-Abbrev}' "
                        "\"$package\" 2>/dev/null | grep -q '^ii '; then\n"
                        '        apt-mark hold "$package"\n'
                        "    fi\n"
                        "done",
                        "flange-apt-hold",
                        *hold_packages,
                    ],
                    label=f"锁定 {len(hold_packages)} 个外部包相关版本...",
                )
            chroot.run(["ldconfig"], label="ldconfig...")
        shutil.rmtree(deb_tmp)

    def _install_extra_firmware(self, rootfs_dir: Path, config: dict):
        """从 canonical source 引用安装额外固件。"""
        extra_firmware = config.get("rootfs", {}).get("extra_firmware", [])
        if not extra_firmware:
            return
        for fw in extra_firmware:
            name = fw["name"]
            self._status(f"同步固件源: {name}")
            fw_dir = self.source.ensure_extra_firmware(name, fw, config=config)
            dest_base = rootfs_dir / fw.get("dest", "lib/firmware")
            for entry in fw.get("files", []):
                if isinstance(entry, dict):
                    src_rel, dest_rel = entry["src"], entry["dest"]
                else:
                    src_rel = dest_rel = entry
                src = fw_dir / src_rel
                if not src.exists():
                    raise FileNotFoundError(f"固件文件不存在: {src}（仓库: {name}）")
                dest = dest_base / dest_rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
            self._status(f"已安装 {len(fw.get('files', []))} 个固件文件 ({name})")

    # ------------------------------------------------------------------
    # 用户 / sudo / root 账号一体化配置
    # ------------------------------------------------------------------

    @staticmethod
    def _real_users(rootfs_cfg: dict) -> dict:
        """返回 canonical rootfs 用户对象。"""
        return rootfs_cfg.get("users") or {}

    def _validate_account_config(self, rootfs_cfg: dict) -> None:
        """对账号子树做编译期校验。

        - default_user 非 None 时必须存在于 users 键集（过滤伪 key 后）
        - disable_root_login=True 且 users 为空时拒绝构建（避免镜像无任何
          普通用户可登录、串口/SSH 全失联；adb 仍可达不算"可登录"）
        """
        users = self._real_users(rootfs_cfg)
        default_user = rootfs_cfg.get("default_user")
        if default_user is not None and default_user not in users:
            raise ValueError(
                f"rootfs.default_user={default_user!r} 不在 rootfs.users 中；"
                f"已声明用户: {sorted(users.keys()) or '(空)'}"
            )
        if rootfs_cfg.get("default_session") and default_user is None:
            raise ValueError("设置 rootfs.default_session 时 rootfs.default_user 不能为空")
        if rootfs_cfg.get("disable_root_login") and not users:
            raise ValueError(
                "rootfs.disable_root_login=True 但 rootfs.users 为空 — "
                "镜像将无任何普通用户可登录、串口/SSH 全失联（adb 仍可达"
                "但不构成可登录通道），请至少声明一个 user 后再启用。"
            )

        remote_login = rootfs_cfg.get("gnome_remote_desktop_login", False)
        if not isinstance(remote_login, bool):
            raise ValueError("rootfs.gnome_remote_desktop_login 必须是布尔值")
        if remote_login:
            if default_user is None:
                raise ValueError("启用 GNOME Remote Login 时 rootfs.default_user 不能为空")
            password = (users.get(default_user) or {}).get("password")
            if not isinstance(password, str) or not password:
                raise ValueError(
                    "启用 GNOME Remote Login 时 rootfs.users."
                    f"{default_user}.password 必须是非空字符串"
                )

    def _configure_users(self, rootfs_dir: Path, config: dict):
        """创建 group / 用户 / 设密码 / sudo / 锁 root / sshd drop-in。

        编排顺序（与 spec rootfs-user-system 对齐）：
          1) 配置校验（_validate_account_config）
          2) groupadd -r -f 全部顶层 groups（幂等创建 system group，系统组）
          3) for each user:
               default_user 固定创建为 UID/GID 1000 的同名用户私有组
               其余用户执行 useradd -m -s <shell> -U <name>
               usermod -aG <merged> <name>
               chpasswd 写密码
               若 sudo=={"nopasswd": True} 写 /etc/sudoers.d/90-<name>
          4) 若声明 root_password 则调用 _set_root_password
          5) 若 disable_root_login 则 passwd -l root 并写 sshd drop-in
          6) 末尾硬校验：shadow root 行 + sshd drop-in 文件 + visudo -cf
          7) 为 default_user 写入 AccountsService 默认图形会话

        旧 board（不写 users / default_user / disable_root_login）行为：
        仅走 (1) (2) (4)，与本次改造前完全一致。
        """
        rootfs_cfg = config.get("rootfs") or {}
        self._validate_account_config(rootfs_cfg)

        groups = list(rootfs_cfg.get("groups") or [])
        users = self._real_users(rootfs_cfg)
        default_user = rootfs_cfg.get("default_user")
        root_password = rootfs_cfg.get("root_password")
        disable_root_login = bool(rootfs_cfg.get("disable_root_login"))

        with ChrootContext(rootfs_dir, self.docker) as chroot:
            # (2) 预创顶层 groups（即便没有 user，下游 udev rule 也可能
            #     依赖 i2c / spi / gpio 等 group 存在）
            if groups:
                self._status(f"创建 group ({len(groups)} 个): {', '.join(groups)}")
                for g in groups:
                    chroot.run(["groupadd", "-r", "-f", g])

            # (3) 创建用户
            sudoers_d_written: list[str] = []
            user_names = list(users)
            if default_user is not None:
                user_names.remove(default_user)
                user_names.insert(0, default_user)
            for name in user_names:
                spec = users[name] or {}
                shell = spec.get("shell", "/bin/bash")
                self._status(f"创建用户 {name!r} (shell={shell})")
                # 默认桌面用户对齐 Ubuntu 首个用户：UID 1000，并以同名
                # GID 1000 用户私有组作为主组；冲突时由 shadow 工具直接失败。
                if name == default_user:
                    chroot.run(["groupadd", "-g", "1000", name])
                    chroot.run(
                        [
                            "useradd",
                            "-m",
                            "-u",
                            "1000",
                            "-g",
                            name,
                            "-s",
                            shell,
                            name,
                        ]
                    )
                else:
                    chroot.run(["useradd", "-m", "-U", "-s", shell, name])

                merged = self._merge_user_groups(groups, spec)
                if merged:
                    chroot.run(["usermod", "-aG", ",".join(merged), name])

                password = spec.get("password")
                if password is not None:
                    chroot.run(["chpasswd"], input=f"{name}:{password}\n")

                sudo_spec = spec.get("sudo", True)
                if isinstance(sudo_spec, dict) and sudo_spec.get("nopasswd"):
                    self._write_sudoers_nopasswd(rootfs_dir, name)
                    sudoers_d_written.append(name)

            # (4) root 密码
            if root_password:
                self._set_root_password_in_chroot(chroot, root_password)

            # (5) disable_root_login：锁 shadow + 写 sshd drop-in
            if disable_root_login:
                self._status("锁定 root 登录通道（passwd -l root + sshd drop-in）")
                chroot.run(["passwd", "-l", "root"])
                self._write_sshd_no_root_drop_in(rootfs_dir)

            # (6) 硬校验
            if root_password:
                self._verify_root_password(rootfs_dir, expect_locked=disable_root_login)
            elif disable_root_login:
                # 无 root_password 但锁了 root：shadow 字段应当以 ! 起首
                self._verify_root_locked(rootfs_dir)
            if disable_root_login:
                self._verify_sshd_no_root(rootfs_dir)
            for name in sudoers_d_written:
                # visudo -cf 在 chroot 内对 drop-in 单文件做语法校验；语法错时
                # 整个 sudoers.d 被 sudo 拒绝读取，提权失效。
                chroot.run(["visudo", "-cf", f"/etc/sudoers.d/90-{name}"])

        self._write_default_session(rootfs_dir, rootfs_cfg)
        self._write_gnome_remote_desktop_credentials(rootfs_dir, rootfs_cfg)

    def _write_default_session(self, rootfs_dir: Path, rootfs_cfg: dict) -> None:
        """通过 AccountsService 设置 default_user 的默认图形会话。"""
        session = rootfs_cfg.get("default_session")
        if not session:
            return
        launchers = (
            rootfs_dir / "usr/share/wayland-sessions" / f"{session}.desktop",
            rootfs_dir / "usr/share/xsessions" / f"{session}.desktop",
        )
        if not any(path.is_file() for path in launchers):
            raise FileNotFoundError(
                f"rootfs.default_session={session!r} 没有对应的 session launcher"
            )

        path = rootfs_dir / "var/lib/AccountsService/users" / rootfs_cfg["default_user"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"[User]\nXSession={session}\n", encoding="utf-8")
        path.chmod(0o600)
        self.docker.run_privileged(["chown", "root:root", str(path)])

    def _write_gnome_remote_desktop_credentials(self, rootfs_dir: Path, rootfs_cfg: dict) -> None:
        """写入 root-only 首启凭据，由 desktop App 配置系统级 RDP。"""
        if not rootfs_cfg.get("gnome_remote_desktop_login"):
            return

        username = rootfs_cfg["default_user"]
        password = rootfs_cfg["users"][username]["password"]
        path = rootfs_dir / "var/lib/flange" / "gnome-remote-desktop-login.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"username": username, "password": password},
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        path.chmod(0o600)
        self.docker.run_privileged(["chown", "root:root", str(path)])

    def _merge_user_groups(self, top_groups: list, spec: dict) -> list:
        """合并 user 实际入组集合：
        - 先取顶层 groups
        - 若 user.sudo == False 则从中扣除 "sudo"
        - 再追加 user.groups 中的额外项（去重保序）
        """
        sudo_spec = spec.get("sudo", True)
        merged: list[str] = []
        for g in top_groups:
            if g == "sudo" and sudo_spec is False:
                continue
            merged.append(g)
        for g in spec.get("groups") or []:
            if g not in merged:
                merged.append(g)
        return merged

    def _write_sudoers_nopasswd(self, rootfs_dir: Path, name: str):
        """写入 /etc/sudoers.d/90-<name>，单行 NOPASSWD ALL，0440 root:root。"""
        path = rootfs_dir / "etc" / "sudoers.d" / f"90-{name}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{name} ALL=(ALL:ALL) NOPASSWD:ALL\n")
        # docker 内文件已是 root 所有；权限设 0440
        self.docker.run_privileged(["chmod", "0440", str(path)])
        self.docker.run_privileged(["chown", "root:root", str(path)])

    def _write_sshd_no_root_drop_in(self, rootfs_dir: Path):
        """写入 /etc/ssh/sshd_config.d/10-flange.conf，禁 root SSH 登录。

        sshd 加载顺序：/etc/ssh/sshd_config 末尾 ``Include sshd_config.d/*.conf``，
        drop-in 设定覆盖主配置；ubuntu-base 默认即如此。
        """
        path = rootfs_dir / "etc" / "ssh" / "sshd_config.d" / "10-flange.conf"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "# flange: disable_root_login=true 下禁止 root 通过 SSH 登录。\n"
            "# adb 调试通道不受影响（adbd 不走 PAM）。\n"
            "PermitRootLogin no\n"
        )

    def _set_root_password_in_chroot(self, chroot, password: str):
        """在已打开的 chroot 上下文中设置 root 密码。

        与 _set_root_password 不同：不重复打开 ChrootContext，避免
        嵌套挂载。供 _configure_users 内部统一使用。
        """
        self._status("设置 root 密码...")
        chroot.run(["chpasswd"], input=f"root:{password}\n")

    def _set_root_password(self, rootfs_dir: Path, password: str):
        """设置 root 密码（独立入口，会自开 ChrootContext）。

        历史接口；新代码应优先走 _configure_users 一次性完成全部账号编排。
        保留此方法仅为内部复用与可能的极小路径调用。

        chpasswd 在 chroot 内执行（通过 qemu-user-static 模拟 arm64），
        读 stdin 的 user:password 行写入 /etc/shadow。

        使用 ChrootContext 确保 /proc /sys /dev 已挂载：chpasswd 通过
        libcrypt 生成盐值时可能读 /dev/urandom，缺失时会静默失败或
        产生无效哈希。

        执行后立即读 /etc/shadow 硬校验 root 行：若密码字段仍是
        锁定态（!/*/空）或格式非法，抛错而非静默产生不可登录镜像。
        """
        with ChrootContext(rootfs_dir, self.docker) as chroot:
            self._set_root_password_in_chroot(chroot, password)
        self._verify_root_password(rootfs_dir)

    def _verify_root_password(self, rootfs_dir: Path, expect_locked: bool = False):
        """校验 /etc/shadow 中 root 行密码字段。

        expect_locked=True 时：允许字段以 ``!`` 起首（passwd -l 后正常状态），
        但去掉 ``!`` 后剩余部分仍应是合法 hash（即"先设密码再锁定"路径）。
        expect_locked=False 时：字段必须是合法 hash。
        """
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
            if expect_locked:
                if not pw_hash.startswith("!"):
                    raise RuntimeError(
                        f"disable_root_login=True 但 /etc/shadow root 字段未锁定: {pw_hash[:40]!r}"
                    )
                inner = pw_hash.lstrip("!")
                if not inner.startswith("$"):
                    raise RuntimeError(f"root 密码哈希格式非预期（去 ! 前缀后）: {inner[:40]!r}")
                self._status(f"root 密码已写入并锁定 (hash: {pw_hash[:13]}...)")
                return
            if pw_hash in ("", "!", "*", "!!", "x"):
                raise RuntimeError(
                    f"root 密码未生效：/etc/shadow 字段仍为 {pw_hash!r}，"
                    f"chpasswd 未成功写入（检查 chroot/qemu 环境）"
                )
            if not pw_hash.startswith("$"):
                raise RuntimeError(f"root 密码哈希格式非预期: {pw_hash[:40]!r}")
            self._status(f"root 密码已写入 (hash: {pw_hash[:12]}...)")
            return
        raise RuntimeError("/etc/shadow 中未找到 root 账号行")

    def _verify_root_locked(self, rootfs_dir: Path):
        """无 root_password 但 disable_root_login=True 时的轻量校验：
        仅要求 root 行的密码字段以 ! 起首，对内容形式不做要求。"""
        shadow = rootfs_dir / "etc" / "shadow"
        for line in shadow.read_text().splitlines():
            if line.startswith("root:"):
                pw = line.split(":")[1] if ":" in line else ""
                if not pw.startswith("!"):
                    raise RuntimeError(
                        f"disable_root_login=True 但 /etc/shadow root 字段未锁定: {pw[:40]!r}"
                    )
                return
        raise RuntimeError("/etc/shadow 中未找到 root 账号行")

    def _verify_sshd_no_root(self, rootfs_dir: Path):
        path = rootfs_dir / "etc" / "ssh" / "sshd_config.d" / "10-flange.conf"
        if not path.exists():
            raise RuntimeError(f"disable_root_login=True 但 sshd drop-in 缺失: {path}")
        content = path.read_text()
        if "PermitRootLogin no" not in content:
            raise RuntimeError(f"sshd drop-in 内容异常，缺少 'PermitRootLogin no': {path}")

    def _install_panel_firmware(self, rootfs_dir: Path, config: dict):
        """编译并安装 panel firmware（mainline panel-mipi-dbi-spi 兼容）。

        config["rootfs"]["panel_firmware"] 格式：
          [
            {
              "src":  "firmware/panel/<name>.txt",   # 相对 components/board/<board>/
              "dest": "<compatible[0]>.bin",         # 相对 rootfs /lib/firmware/
            }
          ]

        text 源由 builder.firmware_panel 编码为 mainline panel.bin 二进制。
        dest 与 DT compatible 的最具体字符串相符——driver 不读 firmware-name
        属性，而是用 ``<compatible[0]>.bin`` 在 /lib/firmware/ 下查找。

        缺源文件 → 直接 raise FileNotFoundError，错误信息含 board 名 + 路径。
        """
        panel_firmwares = config.get("rootfs", {}).get("panel_firmware", [])
        if not panel_firmwares:
            return
        board = config["board"]
        board_root = self.components_root / "board" / board
        dest_base = rootfs_dir / "lib" / "firmware"
        for fw in panel_firmwares:
            src = board_root / fw["src"]
            if not src.exists():
                raise FileNotFoundError(f"panel firmware 文本源不存在: {src} (board: {board})")
            payload = _encode_panel_file(src)
            dest = dest_base / fw["dest"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(payload)
            self._status(
                f"panel firmware: {src.name} → /lib/firmware/{fw['dest']} ({len(payload)} 字节)"
            )

    def _install_hostname(self, rootfs_dir: Path, config: dict):
        """写 /etc/hostname 为 board 名，并补 /etc/hosts 一行让 sudo/glibc 解析通。

        ubuntu-base tarball 默认无 /etc/hostname → systemd-hostnamed 取
        `localhost.localdomain`；sudo 每次启动会延迟约 1s 输出
        `sudo: unable to resolve host localhost.localdomain` 警告（glibc
        getaddrinfo 找不到本机名）。写入 board 名 + /etc/hosts 127.0.1.1
        指向 board 名后告警消失。

        config["rootfs"]["hostname"] 可显式覆盖；否则用 config["board"]。
        """
        rootfs_cfg = config.get("rootfs") or {}
        hostname = rootfs_cfg.get("hostname") or config.get("board") or "flange"
        (rootfs_dir / "etc" / "hostname").write_text(f"{hostname}\n")

        hosts = rootfs_dir / "etc" / "hosts"
        existing = hosts.read_text() if hosts.exists() else ""
        # 已有针对该 hostname 的解析行 → 不动（幂等，允许 overlay/包预置）
        if f" {hostname}\n" in existing or f"\t{hostname}\n" in existing:
            return
        # ubuntu-base 的 /etc/hosts 通常已有 127.0.0.1 localhost；没有也兜底
        if "127.0.0.1" not in existing:
            existing = "127.0.0.1\tlocalhost\n" + existing
        hosts.write_text(existing.rstrip("\n") + f"\n127.0.1.1\t{hostname}\n")
        self._status(f"hostname: {hostname}")
