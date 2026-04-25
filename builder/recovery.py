"""RecoveryBuilder — 各平台 recovery 镜像构建器的公共基类。

recovery 是一个独立的 ext4 文件系统镜像（label=recovery），构建流程：

  Phase 1   解压 ubuntu-base tarball + apt 安装 recovery.packages
  Phase 2   dpkg 安装 recovery.custom_packages 中的 deb（来自 app/ 产物）
            + 拷贝 kernel modules + 应用 recovery-overlay
  Phase 3   写入 /etc/fstab、/etc/flange/recovery-config.json
  Phase 4   ``mke2fs -d`` 把目录直接做成 recovery.img

normal rootfs 与 recovery 复用同一份 ubuntu-base tarball；包集合通过
``config["recovery"]["packages"]`` 与 ``config["recovery"]["custom_packages"]``
独立声明，互不影响 normal 系统。
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from builder.base import ComponentBuilder
from builder.chroot import ChrootContext


# 设备端读取该路径冻结分区表与刷写策略。
RECOVERY_CONFIG_PATH = "etc/flange/recovery-config.json"

# 文件系统 label 与 fstab 中的 LABEL= 一致。
FS_LABEL = "recovery"


def build_recovery_config(config: dict) -> dict:
    """生成 ``/etc/flange/recovery-config.json`` 的内容字典。

    设备端 ``recoveryctl`` 与宿主机 ``flange recovery`` 都把该文件视作分区表
    和刷写策略的事实源；保持纯函数以便单测覆盖。

    schema（v1）::

        {
          "version": 1,
          "board": "...", "product": "...", "variant": "...",
          "transport": "adb",
          "partitions": [
            {
              "name": "rootfs",
              "offset": "0x40000",
              "size": "0x200000",
              "type": "ext4",
              "protected": false
            },
            ...
          ]
        }

    ``protected`` 规则：``type == "raw"`` 一律视为受保护；此外若分区名出现在
    ``recovery.protected_partitions`` 列表中也标记为受保护。recovery 自身
    分区始终保护（设备端不允许从 recovery 内重写自己）。
    """
    recovery_cfg = config.get("recovery") or {}
    protected_set = {*(recovery_cfg.get("protected_partitions") or []), "recovery"}
    transport = recovery_cfg.get("transport", "adb")

    partitions_out: list[dict] = []
    for entry in (config.get("partitions") or {}).get("entries") or []:
        is_raw = entry.get("type") == "raw"
        protected = bool(is_raw or entry.get("name") in protected_set)
        partitions_out.append({
            "name": entry["name"],
            "offset": entry.get("offset", ""),
            "size": entry.get("size", ""),
            "type": entry.get("type", ""),
            "protected": protected,
        })

    return {
        "version": 1,
        "board": config.get("board", ""),
        "product": config.get("product", "default"),
        "variant": config.get("variant", "release"),
        "transport": transport,
        "partitions": partitions_out,
    }


class RecoveryBuilder(ComponentBuilder):
    """recovery 组件构建器基类。

    与 RootfsBuilder 走相同的 docker / chroot / mke2fs 流程，但读取
    ``config["recovery"]`` 子树而非 ``config["rootfs"]``。
    """

    component = "recovery"

    # 文件系统中存放 recovery-config.json 的相对路径（不含前导斜杠）。
    config_rel_path = RECOVERY_CONFIG_PATH

    # 文件系统 label
    fs_label = FS_LABEL

    # ---- 主入口：与 RootfsBuilder 一致，跳过源码克隆 -----------------

    def build(self, config: dict) -> dict:
        self.compile(None, config)
        return self.collect(None, config)

    def configure(self, src_dir: Path, config: dict):
        pass

    def compile(self, src_dir: Path, config: dict):
        self._work_dir = Path(tempfile.mkdtemp(prefix="flange-recovery-"))
        recovery_dir = self._work_dir / "recovery"
        recovery_dir.mkdir()

        self._build_phase1(recovery_dir, config)
        self._build_phase2(recovery_dir, config)
        self._install_fstab(recovery_dir)
        self._install_recovery_config(recovery_dir, config)

        size_mb = self._partition_size_mb(config, "recovery")
        self._output = self._work_dir / "recovery.img"
        self._status(f"生成 recovery.img ({size_mb}MB)...")
        self.docker.run([
            "truncate", "-s", f"{size_mb}M", str(self._output),
        ])
        self.docker.run([
            "mke2fs", "-t", "ext4", "-L", self.fs_label, "-F", "-q",
            "-d", str(recovery_dir), str(self._output),
        ])

    def collect(self, src_dir: Path, config: dict) -> dict:
        return {"recovery": self._output}

    # ---- Phase 1: base 解压 + apt install ---------------------------

    def _build_phase1(self, recovery_dir: Path, config: dict):
        """解压 ubuntu-base tarball 并按 recovery.packages 安装基础包。"""
        self._status("Phase 1: recovery base")
        if self.output:
            self.output.indent()
        try:
            tarball_path = self.source.ensure_rootfs_tarball(config)
            self._status("解压 base tarball...")
            self.docker.run_privileged(
                ["tar", "xf", str(tarball_path), "-C", str(recovery_dir)])
            self.docker.run_privileged(
                ["cp", "/usr/bin/qemu-aarch64-static",
                 str(recovery_dir / "usr" / "bin" / "")])

            with ChrootContext(recovery_dir, self.docker) as chroot:
                apt_cache = recovery_dir / "var" / "cache" / "apt" / "archives"
                apt_cache.mkdir(parents=True, exist_ok=True)
                chroot.bind_mount("/cache/apt", apt_cache)

                self._status("apt-get update...")
                chroot.run(["apt-get", "update"], label="apt-get update...")
                packages = (config.get("recovery") or {}).get("packages") or []
                if packages:
                    self._status(f"apt-get install ({len(packages)} 个包)...")
                    chroot.run(["apt-get", "install", "-y",
                                "--no-install-recommends"] + packages,
                               label=f"安装 {len(packages)} 个包...")
                chroot.run(["apt-get", "clean"])
        finally:
            if self.output:
                self.output.dedent()

    # ---- Phase 2: 自定义 deb + kernel modules + overlay -----------

    def _build_phase2(self, recovery_dir: Path, config: dict):
        """安装 recovery.custom_packages 的 deb，以及 kernel modules 与 overlay。

        与 normal rootfs 不同，recovery 不安装 root_password，也不安装
        extra_firmware（recovery 维护场景不需要 Wi-Fi 等驱动固件）。
        """
        self._status("Phase 2: recovery customize")
        if self.output:
            self.output.indent()
        try:
            self._install_recovery_debs(recovery_dir, config)
            self._install_kernel_modules(recovery_dir, config)
            self._apply_recovery_overlays(recovery_dir, config)
        finally:
            if self.output:
                self.output.dedent()

    def _install_recovery_debs(self, recovery_dir: Path, config: dict):
        """从 app 产物目录挑选 recovery.custom_packages 对应的 deb 安装。"""
        custom_pkgs = (config.get("recovery") or {}).get("custom_packages") or []
        if not custom_pkgs:
            return
        target_dir = self.cache.target_dir
        app_deb_dir = target_dir / "app"
        if not app_deb_dir.is_dir():
            return

        wanted: set[str] = set(custom_pkgs)
        # AppBuilder 的 deb 命名形如 ``<name>_<version>_<arch>.deb``；
        # 取下划线前的 token 与 wanted 集合比对，简单稳定。
        deb_files: list[Path] = []
        for deb in sorted(app_deb_dir.glob("*.deb")):
            stem = deb.stem.split("_", 1)[0]
            if stem in wanted:
                deb_files.append(deb)
        if not deb_files:
            return

        names = [d.name for d in deb_files]
        self._status(f"安装 recovery deb {len(deb_files)} 个: {', '.join(names)}")
        deb_tmp = recovery_dir / "tmp" / "flange-debs"
        deb_tmp.mkdir(parents=True, exist_ok=True)
        for deb in deb_files:
            shutil.copy2(deb, deb_tmp)
        with ChrootContext(recovery_dir, self.docker) as chroot:
            deb_list = [f"/tmp/flange-debs/{d.name}" for d in deb_files]
            chroot.run(["dpkg", "-i", "--force-confnew"] + deb_list,
                       label=f"dpkg -i ({len(deb_files)} 个包)...")
        shutil.rmtree(deb_tmp)

    def _install_kernel_modules(self, recovery_dir: Path, config: dict):
        """把 kernel 组件产物中的模块复制进 recovery rootfs。

        路径与 RootfsBuilder 一致：``target/.../kernel/modules/lib/modules/``。
        """
        target_dir = self.cache.target_dir
        modules_src = target_dir / "kernel" / "modules" / "lib" / "modules"
        if not modules_src.is_dir():
            return
        self._status("安装内核模块到 recovery...")
        dest = recovery_dir / "lib" / "modules"
        dest.mkdir(parents=True, exist_ok=True)
        self.docker.run_privileged(
            ["cp", "-a", f"{modules_src}/.", str(dest)])

    def _apply_recovery_overlays(self, recovery_dir: Path, config: dict):
        """按 rootfs → platform → board 的优先级应用 recovery overlay 文件。

        路径约定（与 normal rootfs 的 overlay 区分，使 recovery 可以单独配置）：
          components/recovery/overlay/                       跨平台 recovery 共用
          components/platform/<p>/recovery-overlay/          平台层 recovery 专用
          components/board/<b>/recovery-overlay/             板级 recovery 专用
        """
        platform = config.get("platform", "")
        board = config.get("board", "")
        for overlay_dir, label in [
            (Path("components/recovery/overlay"), "recovery"),
            (Path(f"components/platform/{platform}/recovery-overlay"), "platform"),
            (Path(f"components/board/{board}/recovery-overlay"), "board"),
        ]:
            if overlay_dir.exists() and any(overlay_dir.iterdir()):
                self._status(f"复制 {label} recovery overlay 文件...")
                self.docker.run_privileged(
                    ["cp", "-a", f"{overlay_dir}/.", str(recovery_dir)])

    # ---- Phase 3: fstab + recovery-config.json -----------------------

    def _install_fstab(self, recovery_dir: Path):
        """写入最小 ``/etc/fstab``：recovery 自身 / + boot 分区 /boot。

        recovery 不挂载 normal rootfs 或 userdata；需要时由 recoveryctl
        显式挂载到独立目录，避免误触 normal 系统的运行时状态。

        ubuntu-base tarball 自带占位 fstab（仅 "# UNCONFIGURED FSTAB FOR BASE
        SYSTEM" 注释，无任何挂载项），需要被覆盖；只有真正声明了 ``LABEL=`` /
        ``UUID=`` / ``/dev/`` 之类挂载项的 fstab 才视为已被 overlay 自定义。
        """
        fstab = recovery_dir / "etc" / "fstab"
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
            f"LABEL={self.fs_label}  /         ext4    defaults   0       1\n"
            "LABEL=boot      /boot     ext4    defaults   0       2\n"
        )
        (recovery_dir / "boot").mkdir(exist_ok=True)

    def _install_recovery_config(self, recovery_dir: Path, config: dict):
        """渲染 recovery-config.json 并写入镜像内的固定路径。"""
        target = recovery_dir / self.config_rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        data = build_recovery_config(config)
        target.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    # ---- 工具 -------------------------------------------------------

    def _partition_size_mb(self, config: dict, name: str) -> int:
        """从 partitions.entries 读取指定分区的大小（MB）。"""
        for entry in (config.get("partitions") or {}).get("entries") or []:
            if entry["name"] == name:
                size = entry["size"]
                if size == "remaining":
                    return 4096  # remaining 默认 4GB（recovery 不应该用 remaining）
                return (int(size, 0) * 512) // (1024 * 1024)
        raise KeyError(f"partitions.entries 中未定义分区: {name}")
