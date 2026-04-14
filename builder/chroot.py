"""Chroot 上下文管理器 — 安全管理 mount/umount 生命周期。"""

import os
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
        # 保存并移除符号链接，否则 cp 会尝试写入不存在的目标
        self._resolv_link = None
        if resolv_dst.is_symlink():
            self._resolv_link = os.readlink(resolv_dst)
            self.docker.run_privileged(["rm", "-f", str(resolv_dst)])
        if resolv_src.exists():
            self.docker.run_privileged(["cp", str(resolv_src), str(resolv_dst)])
        # 阻止 dpkg/apt 在 chroot 内启动服务
        policy_rc = self.rootfs / "usr" / "sbin" / "policy-rc.d"
        policy_rc.parent.mkdir(parents=True, exist_ok=True)
        policy_rc.write_text("#!/bin/sh\nexit 101\n")
        policy_rc.chmod(0o755)
        return self

    def __exit__(self, *exc):
        # 恢复 resolv.conf 符号链接（如果之前被替换）
        resolv_dst = self.rootfs / "etc" / "resolv.conf"
        if self._resolv_link:
            self.docker.run_privileged(["rm", "-f", str(resolv_dst)])
            self.docker.run_privileged(
                ["ln", "-s", self._resolv_link, str(resolv_dst)])
        # 移除 policy-rc.d，恢复目标系统正常服务管理
        policy_rc = self.rootfs / "usr" / "sbin" / "policy-rc.d"
        if policy_rc.exists():
            policy_rc.unlink()
        for mount_point in reversed(self._mounts):
            self.docker.run_privileged(["umount", "-l", str(mount_point)], check=False)
        return False

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
        if fstype: cmd.extend(["-t", fstype])
        cmd.extend([src, str(dest)])
        self.docker.run_privileged(cmd)
        self._mounts.append(dest)

    def _bind(self, src, dest):
        Path(dest).mkdir(parents=True, exist_ok=True)
        self.docker.run_privileged(["mount", "-o", "bind", str(src), str(dest)])
        self._mounts.append(dest)
