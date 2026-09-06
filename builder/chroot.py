"""Chroot 上下文管理器 — 安全管理 mount/umount 生命周期。"""

import os
from pathlib import Path
import tempfile

from builder.docker import DockerRunner


class ChrootContext:
    """自动管理 chroot 环境的 mount/umount。

    用法:
        with ChrootContext(rootfs_dir, docker) as chroot:
            chroot.run(["apt-get", "update"])
            chroot.run(["apt-get", "install", "-y", "pkg"])
        # __exit__ 自动 umount 所有挂载点
    """

    def __init__(self, rootfs_dir: Path, docker: DockerRunner):
        self.rootfs = rootfs_dir
        self.docker = docker
        self._mounts: list[Path] = []
        self._restorations: list[tuple[Path, Path | None]] = []

    def __enter__(self):
        if self._mounts or self._restorations:
            raise RuntimeError("ChrootContext 仍有未清理资源，不能重复进入")
        try:
            self._mount("proc", self.rootfs / "proc", fstype="proc")
            self._mount("sysfs", self.rootfs / "sys", fstype="sysfs")
            self._bind("/dev", self.rootfs / "dev")
            self._bind("/dev/pts", self.rootfs / "dev/pts")
            # 构建期 DNS 与服务启动策略不得覆盖目标系统原有配置。
            resolv_src = Path("/etc/resolv.conf")
            if resolv_src.exists():
                resolv_dst = self.rootfs / "etc" / "resolv.conf"
                self._preserve_file(resolv_dst)
                self.docker.run_privileged(["cp", str(resolv_src), str(resolv_dst)])
            policy_rc = self.rootfs / "usr" / "sbin" / "policy-rc.d"
            self._preserve_file(policy_rc)
            policy_rc.write_text("#!/bin/sh\nexit 101\n")
            policy_rc.chmod(0o755)
        except BaseException as error:
            # __enter__ 失败时 Python 不会调用 __exit__，必须在这里回滚。
            self._cleanup(error)
            raise
        return self

    def __exit__(self, exc_type, error, traceback):
        self._cleanup(error)
        return False

    def _preserve_file(self, path: Path) -> None:
        """原子保存文件或链接，恢复时保留内容、权限、所有权及链接目标。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        backup = None
        if path.exists() or path.is_symlink():
            if not path.is_file() and not path.is_symlink():
                raise ValueError(f"chroot 临时配置必须是文件或符号链接：{path}")
            descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.flange-", dir=path.parent)
            os.close(descriptor)
            backup = Path(name)
            try:
                path.replace(backup)
            except BaseException:
                backup.unlink(missing_ok=True)
                raise
        self._restorations.append((path, backup))

    @staticmethod
    def _restore_file(path: Path, backup: Path | None) -> None:
        if backup is None:
            path.unlink(missing_ok=True)
        else:
            backup.replace(path)

    def _cleanup(self, primary: BaseException | None = None) -> None:
        """全部资源独立清理；失败不会跳过卸载，也不会覆盖原构建异常。"""
        failures: list[tuple[str, BaseException]] = []
        for path, backup in reversed(self._restorations[:]):
            try:
                self._restore_file(path, backup)
            except BaseException as error:
                failures.append((f"恢复 chroot 文件失败：{path}", error))
            else:
                self._restorations.remove((path, backup))
        for mount_point in reversed(self._mounts[:]):
            try:
                # 普通卸载必须成功才能继续发布；lazy detach 会掩盖仍被占用的挂载。
                self.docker.run_privileged(["umount", str(mount_point)])
            except BaseException as error:
                failures.append((f"卸载 chroot 挂载失败：{mount_point}", error))
            else:
                self._mounts.remove(mount_point)
        if not failures:
            return
        error = primary if primary is not None else failures[0][1]
        for action, failure in failures:
            error.add_note(f"{action}（{type(failure).__name__}: {failure}）")
        if primary is None:
            raise error

    def run(self, cmd: list, *, label: str = "", env: dict = None, **kwargs):
        """在 chroot 内执行命令"""
        chroot_env = {"DEBIAN_FRONTEND": "noninteractive"}
        if env:
            chroot_env.update(env)
        self.docker.run_privileged(["chroot", str(self.rootfs)] + cmd,
                                   label=label, env=chroot_env, **kwargs)

    def bind_mount(self, src: str, dest: Path = None):
        dest = dest or (self.rootfs / src.lstrip("/"))
        self._bind(src, dest)

    def _mount(self, src, dest, fstype=None):
        Path(dest).mkdir(parents=True, exist_ok=True)
        cmd = ["mount"]
        if fstype:
            cmd.extend(["-t", fstype])
        cmd.extend([src, str(dest)])
        self.docker.run_privileged(cmd)
        self._mounts.append(dest)

    def _bind(self, src, dest):
        Path(dest).mkdir(parents=True, exist_ok=True)
        self.docker.run_privileged(["mount", "-o", "bind", str(src), str(dest)])
        self._mounts.append(dest)
