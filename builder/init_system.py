"""init 系统抽象：发行版声明 init，App 服务的设备操作按 init 生成命令。

flange 不翻译服务描述：每种 init 由 App 提供原生服务文件（systemd unit 或
OpenRC 脚本），这里只描述"文件放哪里"和"设备上怎么操作服务"。

OpenRC 约定：flange App 的服务脚本 MUST 把 pidfile 设为 ``/run/<服务名>.pid``
（start-stop-daemon 为服务进程，supervise-daemon 为其监督进程），并把输出写到
``/var/log/<服务名>.log``（``output_log``/``error_log``），`app debug` 与
`app log` 依赖这两个路径。
"""

from __future__ import annotations

from dataclasses import dataclass


class InitSystemError(ValueError):
    """init 系统不支持的设备操作或未知 init 名称。"""


@dataclass(frozen=True)
class InitSystem:
    name: str

    def reload(self) -> list[str] | None:
        """服务文件更新后需要执行的重载命令；OpenRC 每次启动都重读脚本。"""
        return ["systemctl", "daemon-reload"] if self.name == "systemd" else None

    def restart(self, service: str) -> list[str]:
        if self.name == "systemd":
            return ["systemctl", "restart", service]
        return ["rc-service", service, "restart"]

    def is_active(self, service: str) -> list[str]:
        if self.name == "systemd":
            return ["systemctl", "is-active", "--quiet", service]
        return ["rc-service", "--quiet", service, "status"]

    def main_pid(self, service: str) -> list[str]:
        if self.name == "systemd":
            return ["systemctl", "show", service, "--property", "MainPID", "--value"]
        return [
            "sh", "-c",
            'p=$(cat "/run/$1.pid") || exit 1\n'
            'case "$p" in ""|*[!0-9]*|0) exit 1;; esac\n'
            'exe=$(readlink "/proc/$p/exe") || exit 1\n'
            'case "$exe" in */supervise-daemon|*/supervise-daemon\\ \\(deleted\\))\n'
            '  child=$(cat "${RC_SVCDIR:-/run/openrc}/options/$1/child_pid") || exit 1\n'
            '  case "$child" in ""|*[!0-9]*|0) exit 1;; esac\n'
            '  parent=$(awk \'/^PPid:/ {print $2}\' "/proc/$child/status") || exit 1\n'
            '  [ "$parent" = "$p" ] || exit 1\n'
            '  p=$child;;\n'
            'esac\n'
            'kill -0 "$p" || exit 1\n'
            'printf "%s\\n" "$p"',
            "flange-openrc-pid", service,
        ]

    def log(
        self, service: str, *, lines: int | None = None, since: str | None = None,
        follow: bool = False,
    ) -> list[str]:
        if self.name == "systemd":
            command = ["journalctl", "-u", service, "--no-pager"]
            if lines is not None:
                command += ["-n", str(lines)]
            if since:
                command += ["--since", since]
            if follow:
                command.append("-f")
            return command
        if since:
            raise InitSystemError("OpenRC 服务日志是普通文件，不支持 --since")
        command = ["tail", "-n", str(lines) if lines is not None else "+1"]
        if follow:
            command.append("-F")
        return command + [f"/var/log/{service}.log"]


SYSTEMD = InitSystem("systemd")
OPENRC = InitSystem("openrc")
_INIT_SYSTEMS = {item.name: item for item in (SYSTEMD, OPENRC)}


def get_init_system(name: str) -> InitSystem:
    try:
        return _INIT_SYSTEMS[name]
    except KeyError:
        raise InitSystemError(
            f"未知 init 系统 {name!r}；可用：{', '.join(_INIT_SYSTEMS)}"
        ) from None
