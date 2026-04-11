"""Chroot 上下文管理器 — 安全管理 mount/umount 生命周期。"""

from pathlib import Path
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
        self._mounts = []

    def __enter__(self):
        self._mount("proc", self.rootfs / "proc", fstype="proc")
        self._mount("sysfs", self.rootfs / "sys", fstype="sysfs")
        self._bind("/dev", self.rootfs / "dev")
        self._bind("/dev/pts", self.rootfs / "dev/pts")
        # DNS 解析：复制宿主 resolv.conf 到 chroot 内
        resolv_src = Path("/etc/resolv.conf")
        resolv_dst = self.rootfs / "etc" / "resolv.conf"
        if resolv_src.exists():
            self.docker.run_privileged(["cp", str(resolv_src), str(resolv_dst)])
        return self

    def __exit__(self, *exc):
        for mount_point in reversed(self._mounts):
            self.docker.run_privileged(["umount", "-l", str(mount_point)], check=False)
        return False

    def run(self, cmd: list, **kwargs):
        """在 chroot 内执行命令"""
        self.docker.run_privileged(["chroot", str(self.rootfs)] + cmd, **kwargs)

    def bind_mount(self, src: str, dest: Path = None):
        dest = dest or (self.rootfs / src.lstrip("/"))
        self._bind(src, dest)

    def _mount(self, src, dest, fstype=None):
        Path(dest).mkdir(parents=True, exist_ok=True)
        cmd = ["mount"]
        if fstype: cmd.extend(["-t", fstype])
        cmd.extend([src, str(dest)])
        self.docker.run_privileged(cmd)
        self._mounts.append(dest)

    def _bind(self, src, dest):
        Path(dest).mkdir(parents=True, exist_ok=True)
        self.docker.run_privileged(["mount", "-o", "bind", str(src), str(dest)])
        self._mounts.append(dest)
