"""能力所需后台 daemon 的生命周期管理，全部交由 systemd。

对应 race-checklist.md 知识 #10 —— 该项**不迁移**，而是消灭其存在前提。

既有 shell 实现自制保活循环：

    while [ -f $TAG_FILE ]; do start-stop-daemon -Sqx $@; sleep .5; done

其 spawn 守卫读「状态文件内容非空」而循环退出条件读「状态文件存在」，
disconnect recovery 只清空该文件不删除，于是守卫失效、旧循环永不退出，
每次 disconnect 净泄漏一个永生循环。ROCK 5B 实测：开机 11 分钟堆积
360 余个并发循环，多循环争抢同一 FunctionFS ep0，USB 每 2 秒断连一次，
adbd 被反复 kill，adb 完全不可用。

改用 systemd unit 后，保活由 unit 的 Restart= 声明承担，进程在 systemd
的 cgroup 下运行，输出进 journal。自制循环这一整类 bug 不再可能发生。
"""

from __future__ import annotations

import logging
import subprocess

log = logging.getLogger(__name__)

# 能力的 daemon unit 统一前缀，与 App 安装的 unit 文件名对应。
UNIT_PREFIX = "usbmoded-"

SYSTEMCTL_TIMEOUT = 30


class DaemonError(Exception):
    """daemon 操作失败。"""


def unit_name(daemon: str) -> str:
    """daemon 名到 systemd unit 名。"""
    return f"{UNIT_PREFIX}{daemon}.service"


def _systemctl(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    cmd = ["systemctl", *args]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=SYSTEMCTL_TIMEOUT
        )
    except FileNotFoundError as exc:
        raise DaemonError("systemctl 不可用 —— 本服务依赖 systemd 管理 daemon") from exc
    except subprocess.TimeoutExpired as exc:
        raise DaemonError(f"systemctl {' '.join(args)} 超时") from exc
    if check and result.returncode != 0:
        raise DaemonError(
            f"systemctl {' '.join(args)} 失败（{result.returncode}）："
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result


def start(daemon: str) -> None:
    """启动 daemon 对应的 unit。

    不做「已运行则跳过」的判断 —— systemctl start 本身对已运行的 unit
    是幂等的，重复判断只会引入 TOCTOU 窗口。
    """
    unit = unit_name(daemon)
    log.info("启动 daemon unit：%s", unit)
    _systemctl("start", unit)


def stop(daemon: str) -> None:
    """停止 daemon 对应的 unit。

    unit 未运行时 systemctl stop 返回成功，因此本函数可重入 ——
    能力的 stop() 契约要求「未启动时调用应为空操作」。
    """
    unit = unit_name(daemon)
    log.info("停止 daemon unit：%s", unit)
    _systemctl("stop", unit)


def restart(daemon: str) -> None:
    """重启 daemon 对应的 unit。

    断连恢复路径用它让 daemon 重新获取 endpoint（知识 #8）——
    注意该路径只重启 daemon，不触碰 configfs 链接。
    """
    unit = unit_name(daemon)
    log.info("重启 daemon unit：%s", unit)
    _systemctl("restart", unit)


def is_active(daemon: str) -> bool:
    """查询 daemon 是否在运行。"""
    result = _systemctl("is-active", "--quiet", unit_name(daemon), check=False)
    return result.returncode == 0


def exists(daemon: str) -> bool:
    """查询 unit 文件是否存在。

    能力启用前用它做前置检查，避免把「unit 没装」误报成「daemon 启动失败」。
    """
    result = _systemctl(
        "list-unit-files", "--no-legend", unit_name(daemon), check=False
    )
    return result.returncode == 0 and bool(result.stdout.strip())
