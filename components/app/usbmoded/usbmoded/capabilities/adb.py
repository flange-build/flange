"""adb 能力：FunctionFS + adbd。

对应 usb-capability-layer spec「adb 能力」。

adbd 在 prepare 阶段启动，不在 start 阶段 —— FunctionFS 要求 daemon
先打开 ep0 写入描述符，实例才会 ready，gadget 才能 bind。既有 shell
实现同样如此（adb_prepare 里调 usb_start_daemon）。
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any

from ..capability import (
    ORDER_ADB,
    BaseCapability,
    CapabilityContext,
    CapabilityError,
    CapabilityStatus,
)
from . import daemon

DAEMON = "adbd"
ENV_DIR = Path("/run/usbmoded")

# 等待 daemon 真正打开 endpoint 的上限，200 × 0.01s = 2s，
# 与既有 shell 实现的 usb_wait_files 一致。
OPEN_WAIT_ATTEMPTS = 200
OPEN_WAIT_INTERVAL = 0.01


def wait_endpoint_opened(endpoint: Path, attempts: int = OPEN_WAIT_ATTEMPTS) -> bool:
    """等待 endpoint 被某个进程实际打开。

    关键：**不能用 endpoint 文件是否存在来判断**。FunctionFS 挂载后
    ep inode 即永久存在，与 daemon 是否打开它完全无关 —— 既有实现的
    注释专门标注过这一点。这里遍历 /proc/<pid>/fd 查找指向该 endpoint
    的描述符，这才是「daemon 已就绪」的真实判据。

    不按进程名匹配，因此不依赖 daemon 叫什么；只关心 endpoint 有没有
    被打开。
    """
    target = str(endpoint)
    for _ in range(attempts):
        if _endpoint_is_open(target):
            return True
        time.sleep(OPEN_WAIT_INTERVAL)
    return False


def _endpoint_is_open(target: str) -> bool:
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        fd_dir = Path("/proc") / entry / "fd"
        try:
            for fd in os.listdir(fd_dir):
                try:
                    if os.readlink(fd_dir / fd) == target:
                        return True
                except OSError:
                    continue
        except OSError:
            # 进程在遍历期间退出，或无权限读取 —— 都不是错误。
            continue
    return False


def _is_mounted(path: Path) -> bool:
    try:
        return path.is_mount()
    except OSError:
        return False


class AdbCapability(BaseCapability):
    """Android Debug Bridge 调试通道。"""

    name = "adb"
    instances = ("ffs.adb",)
    kernel_order = ORDER_ADB
    conflicts = frozenset()
    default_params: dict[str, Any] = {
        "mountpoint": "/dev/usb-ffs/adb",
        "uid": 2000,
        "gid": 2000,
        # adbd 交互式 shell。以 login shell 启动，读 /etc/profile 与
        # /root/.bashrc，与 ssh 登录体验一致。
        "shell": "/bin/bash",
        # 与 USB 并行开启的网络 adb 端口。ADB 36 standalone adbd 需显式
        # 指定；旧 vendor adbd 内建监听 5555 且忽略此值。
        "tcp_port": 5555,
    }

    def _mountpoint(self, ctx: CapabilityContext) -> Path:
        return Path(ctx.params.get("mountpoint", self.default_params["mountpoint"]))

    def prepare(self, ctx: CapabilityContext) -> None:
        params = {**self.default_params, **ctx.params}
        mountpoint = Path(params["mountpoint"])

        # FFS 的挂载源必须是 configfs 中 ffs.<name> 实例的 <name> 部分。
        instance_tag = self.instances[0].split(".", 1)[1]

        mountpoint.mkdir(parents=True, exist_ok=True)
        if not _is_mounted(mountpoint):
            # no_disconnect=1：daemon 短暂退出时不立即拆除 FFS，
            # 给重启留出窗口，避免 gadget 侧看到实例消失。
            opts = f"uid={params['uid']},gid={params['gid']},no_disconnect=1"
            result = subprocess.run(
                ["mount", "-t", "functionfs", "-o", opts, instance_tag, str(mountpoint)],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0 and not _is_mounted(mountpoint):
                raise CapabilityError(
                    f"挂载 FunctionFS 失败：{mountpoint}: {result.stderr.strip()}"
                )

        self._write_env(params)

        if not daemon.exists(DAEMON):
            raise CapabilityError(
                f"缺少 {daemon.unit_name(DAEMON)} —— adb 能力依赖该 unit 管理 adbd"
            )
        daemon.start(DAEMON)

        # 等 adbd 真正持有 ep1，再让上层去绑定 UDC。
        if not wait_endpoint_opened(mountpoint / "ep1"):
            raise CapabilityError(
                f"adbd 未在预期时间内打开 {mountpoint}/ep1 —— "
                f"检查 journalctl -u {daemon.unit_name(DAEMON)}"
            )

    def stop(self, ctx: CapabilityContext) -> None:
        daemon.stop(DAEMON)

    def status(self, ctx: CapabilityContext) -> CapabilityStatus:
        mountpoint = self._mountpoint(ctx)
        active = daemon.is_active(DAEMON) and _endpoint_is_open(str(mountpoint / "ep1"))
        return CapabilityStatus(
            name=self.name,
            active=active,
            detail=f"mount={_is_mounted(mountpoint)} daemon={daemon.is_active(DAEMON)}",
        )

    @staticmethod
    def _write_env(params: dict) -> None:
        """把能力参数交给 adbd 的 systemd unit。

        unit 以 EnvironmentFile=- 读取本文件，因此文件不存在时 unit 仍可
        启动并使用 adbd 自身的默认值。
        """
        ENV_DIR.mkdir(parents=True, exist_ok=True)
        (ENV_DIR / "adbd.env").write_text(
            f"ADBD_SHELL={params['shell']}\n"
            f"ADB_TCP_PORT={params['tcp_port']}\n"
        )
