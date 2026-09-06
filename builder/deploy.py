"""准确产物驱动的设备部署、运行、测试与调试会话。"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from typing import Protocol, Sequence

from builder.app_model import AppBuildReport
from builder.packaging import get_backend
from builder.artifacts import ArtifactManifest
from builder.locking import atomic_write
from builder.locking import FileLock
from builder.workspace import WorkspaceContext


class DeployError(RuntimeError):
    """设备身份、产物或生命周期操作不满足契约。"""


class DeviceTransport(Protocol):
    serial: str

    def shell(self, argv: Sequence[str], **kwargs) -> subprocess.CompletedProcess: ...
    def push(self, source: Path, destination: str) -> None: ...


def _run_checked(
    argv: list[str], *, capture_output=False, check=True, timeout=None, cwd=None
) -> subprocess.CompletedProcess:
    try:
        output = (
            {"capture_output": True}
            if capture_output
            else {"stdout": sys.stdout, "stderr": sys.stderr}
        )
        return subprocess.run(argv, check=check, text=True, timeout=timeout, cwd=cwd, **output)
    except FileNotFoundError as exc:
        raise DeployError(f"命令不存在：{argv[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise DeployError(
            f"命令失败（exit {exc.returncode}）：{shlex.join(argv)}\n{detail}"
        ) from exc


def _adb_shell_argv(serial: str, argv: Sequence[str], *, pty=False) -> list[str]:
    return ["adb", "-s", serial, "shell", *(["-t"] if pty else []), shlex.join(argv)]


def list_adb_devices() -> dict[str, str]:
    output = _run_checked(["adb", "devices"], capture_output=True).stdout
    return {
        fields[0]: fields[1]
        for line in output.splitlines()[1:]
        if len(fields := line.split()) >= 2 and not fields[0].startswith("*")
    }


def select_adb_device(serial: str | None = None) -> str:
    devices = list_adb_devices()
    if serial:
        if devices.get(serial) != "device":
            raise DeployError(
                f"ADB 设备 {serial!r} 不可用（状态：{devices.get(serial, '未发现')}）"
            )
        return serial
    ready = [name for name, state in devices.items() if state == "device"]
    if len(ready) != 1:
        raise DeployError("需要唯一在线 ADB 设备；使用 --serial 明确选择：" + ", ".join(ready))
    return ready[0]


class AdbTransport:
    def __init__(self, serial: str) -> None:
        self.serial = serial

    def shell(
        self, argv: Sequence[str], *, pty=False, capture_output=False, check=True, timeout=None
    ) -> subprocess.CompletedProcess:
        return _run_checked(
            _adb_shell_argv(self.serial, argv, pty=pty),
            capture_output=capture_output,
            check=check,
            timeout=timeout,
        )

    def push(self, source: Path, destination: str) -> None:
        _run_checked(
            ["adb", "-s", self.serial, "push", str(source), destination], capture_output=True
        )


class DeviceSession:
    """成功、失败和中断均保留设备与产物关联的机器可读记录。"""

    def __init__(
        self,
        context: WorkspaceContext,
        report: AppBuildReport | ArtifactManifest,
        action: str,
        serial: str,
    ) -> None:
        identifier = f"{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}-{uuid.uuid4().hex[:10]}"
        self.directory = context.target_dir / "sessions" / identifier
        self.directory.mkdir(parents=True)
        self.path = self.directory / "session.json"
        self.data = {
            "schema_version": 1,
            "id": identifier,
            "action": action,
            "target": asdict(context.target),
            "device": {"transport": "adb", "serial": serial},
            "artifact_identity": report.identity,
            "artifacts": (
                {item.resource_id: item.identity for item in report.ordered}
                if isinstance(report, AppBuildReport)
                else {report.task_id: report.identity}
            ),
            "status": "running",
            "started_at": time.time(),
            "report_path": str(self.path),
        }
        self.save()

    def save(self) -> None:
        atomic_write(self.path, json.dumps(self.data, ensure_ascii=False, indent=2) + "\n")

    def finish(self, status: str, *, exit_code=0, error=None) -> dict:
        self.data.update(status=status, exit_code=exit_code, finished_at=time.time())
        if error:
            self.data["error"] = str(error)
        self.save()
        return self.data


def _preflight(
    context: WorkspaceContext, report: AppBuildReport, transport: DeviceTransport
) -> str:
    if report.target != asdict(context.target) or not report.validate():
        raise DeployError("当前 target 或实际产物与构建报告不匹配；请重新构建")
    backend = _deployment_backend(report)
    expected = backend.architecture(report.architecture)
    actual = transport.shell(backend.architecture_command(), capture_output=True).stdout.strip()
    if actual != expected:
        raise DeployError(f"设备架构 {actual!r} 与构建目标 {expected!r} 不匹配")
    return actual


def _deployment_backend(report: AppBuildReport):
    formats = {item.format for item in report.runtime_packages}
    if not formats:
        raise DeployError("该 App 闭包没有可部署的 runtime 包")
    if len(formats) != 1:
        raise DeployError("一次设备部署不能混用多种包格式")
    return get_backend(next(iter(formats)), getattr(report, "layer_stack", None))


def _deploy(report: AppBuildReport, transport: DeviceTransport, session: DeviceSession) -> None:
    backend = _deployment_backend(report)
    remote_dir = f"/tmp/flange-{session.data['id']}"
    transport.shell(["mkdir", "-p", remote_dir])
    remote_paths = []
    try:
        for index, package in enumerate(report.runtime_packages):
            path = package.path
            remote = f"{remote_dir}/{index}-{path.name}"
            transport.push(path, remote)
            expected = sha256(path.read_bytes()).hexdigest()
            actual = transport.shell(["sha256sum", remote], capture_output=True).stdout.split()[0]
            if actual != expected:
                raise DeployError(f"设备收到的包内容校验失败：{path.name}")
            remote_paths.append(remote)
        transport.shell(backend.install_command(remote_paths), capture_output=True)
    finally:
        transport.shell(["rm", "-rf", remote_dir], check=False, capture_output=True)


def _runtime_command(report: AppBuildReport, args: Sequence[str]) -> list[str]:
    root = report.root()
    if root.app_type in {"exec", "test"} and root.executable:
        return [root.executable, *args]
    if root.app_type == "service":
        if args:
            raise DeployError("service 默认运行方式不接受额外 argv")
        return ["systemctl", "restart", root.service_unit]
    raise DeployError(f"App 类型 {root.app_type!r} 没有默认运行入口")


def _debug(
    context: WorkspaceContext,
    report: AppBuildReport,
    transport: DeviceTransport,
    session: DeviceSession,
    args: Sequence[str],
    mode: str,
    port: int,
) -> None:
    root = report.root()
    if context.target.variant != "debug":
        raise DeployError("GDB 调试需要 debug target")
    if root.app_type not in {"exec", "service"}:
        raise DeployError("默认 GDB 只支持 exec/service App")
    session.data["debug"] = {
        "mode": mode,
        "source_dir": root.debug_source_dir,
        "compile_source_dir": root.compile_source_dir,
        "symbol_tree": str(root.install_dir),
        "executable": root.executable,
        "transport": "adb shell" if mode == "target" else "gdb remote over adb forward",
        "port": port if mode == "remote" else None,
    }
    pid = None
    if root.app_type == "service":
        if args:
            raise DeployError("service GDB 不接受额外 argv")
        pid = transport.shell(
            ["systemctl", "show", root.service_unit, "--property", "MainPID", "--value"],
            capture_output=True,
        ).stdout.strip()
        if not pid.isdecimal() or int(pid) <= 0:
            raise DeployError(f"service {root.service_unit} 没有运行中的 MainPID；请先 app run")
        if mode == "remote":
            executable = transport.shell(
                ["readlink", f"/proc/{pid}/exe"], capture_output=True
            ).stdout.strip()
            symbol = root.install_dir / executable.lstrip("/")
            if (
                not executable.startswith("/")
                or ".." in Path(executable).parts
                or not symbol.is_file()
            ):
                raise DeployError(f"服务进程的符号文件不在当前 App 安装清单中：{executable}")
            session.data["debug"]["executable"] = executable
    session.save()
    if mode == "target":
        transport.shell(["gdb", "--version"], capture_output=True)
        source_target = f"/tmp/flange-source-{session.data['id']}"
        transport.push(Path(root.debug_source_dir), source_target)
        command = [
            "gdb",
            "-ex",
            f"directory {source_target}",
            "-ex",
            f"set substitute-path {root.compile_source_dir} {source_target}",
        ]
        command += ["-p", pid] if pid else ["--args", root.executable, *args]
        session.data["debug"]["source_mapping"] = {root.compile_source_dir: source_target}
        session.save()
        try:
            transport.shell(command, pty=True)
        finally:
            transport.shell(["rm", "-rf", source_target], capture_output=True, check=False)
        return
    debugger = shutil.which("gdb-multiarch") or shutil.which("gdb")
    if not debugger:
        raise DeployError("remote 模式需要宿主 gdb-multiarch 或支持目标架构的 gdb")
    transport.shell(["gdbserver", "--version"], capture_output=True)
    endpoint = f"tcp:{port}"
    _run_checked(
        ["adb", "-s", transport.serial, "forward", endpoint, endpoint], capture_output=True
    )
    server_args = ["gdbserver", "--once"]
    server_args += ["--attach", f":{port}", pid] if pid else [f":{port}", root.executable, *args]
    log_path = session.directory / "gdbserver.log"
    server = None
    try:
        with log_path.open("w") as log:
            server = subprocess.Popen(
                _adb_shell_argv(transport.serial, server_args), stdout=log, stderr=log, text=True
            )
            deadline = time.monotonic() + 10
            while "Listening on port" not in log_path.read_text():
                if server.poll() is not None or time.monotonic() >= deadline:
                    raise DeployError(f"gdbserver 未能开始监听：{log_path.read_text().strip()}")
                time.sleep(0.1)
            command = [
                debugger,
                "-ex",
                f"set sysroot {root.install_dir}",
                "-ex",
                f"directory {root.debug_source_dir}",
                "-ex",
                f"set substitute-path {root.compile_source_dir} {root.debug_source_dir}",
                "-ex",
                f"target remote localhost:{port}",
            ]
            executable = session.data["debug"]["executable"]
            if executable:
                command.insert(1, str(root.install_dir / executable.lstrip("/")))
            session.data["debug"].update(
                host_command=command,
                server_command=server_args,
                server_log=str(log_path),
                endpoint=f"localhost:{port}",
            )
            session.save()
            _run_checked(command)
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
        _run_checked(["adb", "-s", transport.serial, "forward", "--remove", endpoint], check=False)


def operate_report(
    context: WorkspaceContext, report: AppBuildReport, action: str, **options
) -> dict:
    """会话期间锁定目标产物，避免构建或清理替换正在读取的符号与包。"""
    object.__setattr__(report, "layer_stack", context.layer_stack)
    with FileLock(context.build_root / "locks" / f"{context.target.key}.lock"):
        return _operate_report(context, report, action, **options)


def _operate_report(
    context: WorkspaceContext,
    report: AppBuildReport,
    action: str,
    *,
    serial=None,
    args: Sequence[str] = (),
    lines=None,
    since=None,
    follow=True,
    timeout=60,
    debug_mode="target",
    port=2345,
    transport: DeviceTransport | None = None,
) -> dict:
    """执行设备会话；测试失败返回含退出状态的持久化结果。"""
    if timeout <= 0 or not 1 <= port <= 65535 or (lines is not None and lines < 0):
        raise DeployError("timeout/port/lines 参数超出允许范围")
    if action != "deploy":
        root = report.root()
        if action in {"run", "test"}:
            _runtime_command(report, args)
        if action == "debug" and (
            context.target.variant != "debug"
            or root.app_type not in {"exec", "service"}
            or not root.debug_source_dir
        ):
            raise DeployError("默认 GDB 需要 debug target 的 exec/service 产物与源码清单")
        if action == "debug" and os.environ.get("FLANGE_NO_INTERACTION") == "1":
            raise DeployError(
                "GDB 需要交互终端；请取消 FLANGE_NO_INTERACTION 后在终端执行 app debug"
            )
        if action == "log" and root.app_type != "service":
            raise DeployError("默认日志源仅支持 service App")
    if action not in {"deploy", "run", "test", "debug", "log"}:
        raise DeployError(f"未知设备操作：{action}")
    if not report.validate():
        raise DeployError("App 产物校验失败，请重新构建")
    device = transport or AdbTransport(select_adb_device(serial))
    session = DeviceSession(context, report, action, device.serial)
    try:
        session.data["device"]["architecture"] = _preflight(context, report, device)
        if action in {"deploy", "run", "test", "debug"}:
            _deploy(report, device, session)
        root = report.root() if action != "deploy" else None
        if action == "run":
            if root.app_type == "service":
                device.shell(["systemctl", "daemon-reload"])
            result = device.shell(_runtime_command(report, args), check=False, capture_output=True)
            session.data.update(stdout=result.stdout, stderr=result.stderr)
            if result.returncode:
                return session.finish("failed", exit_code=result.returncode)
        elif action == "test":
            command = (
                ["systemctl", "is-active", "--quiet", root.service_unit]
                if root.app_type == "service"
                else _runtime_command(report, args)
            )
            stdout_path, stderr_path = (
                session.directory / "stdout.log",
                session.directory / "stderr.log",
            )
            session.data["test"] = {
                "command": command,
                "timeout_seconds": timeout,
                "stdout_path": str(stdout_path),
                "stderr_path": str(stderr_path),
            }
            session.save()
            try:
                if root.app_type == "service":
                    preparation = [
                        ["systemctl", "daemon-reload"],
                        ["systemctl", "restart", root.service_unit],
                    ]
                    session.data["test"]["preparation_commands"] = preparation
                    session.save()
                    for preparation_command in preparation:
                        device.shell(preparation_command, capture_output=True, timeout=timeout)
                result = device.shell(command, capture_output=True, check=False, timeout=timeout)
            except subprocess.TimeoutExpired as exc:

                def decoded(value):
                    return (
                        value.decode(errors="replace")
                        if isinstance(value, bytes)
                        else (value or "")
                    )

                stdout_path.write_text(decoded(exc.stdout))
                stderr_path.write_text(decoded(exc.stderr))
                raise
            stdout_path.write_text(result.stdout or "")
            stderr_path.write_text(result.stderr or "")
            return session.finish(
                "passed" if result.returncode == 0 else "failed", exit_code=result.returncode
            )
        elif action == "debug":
            _debug(context, report, device, session, args, debug_mode, port)
        elif action == "log":
            if root.app_type != "service":
                raise DeployError("默认日志源仅支持 service App")
            command = ["journalctl", "-u", root.service_unit, "--no-pager"]
            if lines is not None:
                command += ["-n", str(lines)]
            if since:
                command += ["--since", since]
            if follow:
                command.append("-f")
            session.data["log"] = {"command": command}
            device.shell(command)
        elif action != "deploy":
            raise DeployError(f"未知设备操作：{action}")
        return session.finish("succeeded")
    except subprocess.TimeoutExpired as exc:
        return session.finish("timed_out", exit_code=124, error=exc)
    except KeyboardInterrupt:
        session.finish("interrupted", exit_code=130)
        raise
    except BaseException as exc:
        session.finish("failed", exit_code=1, error=exc)
        raise
