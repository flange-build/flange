"""App 热部署、运行、日志与调试——通过 ADB 操作单个应用。"""

from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from builder.app_list import list_all
from builder.app_spec import AppSpec, load_spec
from builder.config.canonical import userspace_arch
from builder.config.loader import load_current_config
from builder.deb import _map_arch
from builder.oot_mounts import CONTAINER_PROJECT_ROOT, oot_volume_arguments
from builder.paths import PROJECT_ROOT, build_dir


class DeployError(RuntimeError):
    """设备生命周期操作无法安全继续。"""


def _run_checked(
    argv: list[str],
    *,
    capture_output: bool = False,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess:
    """执行 argv，并把进程错误转换为可由 CLI 统一呈现的异常。"""
    kwargs: dict = {"check": True}
    if capture_output:
        kwargs.update(capture_output=True, text=True)
    if cwd is not None:
        kwargs["cwd"] = cwd
    try:
        return subprocess.run(argv, **kwargs)
    except FileNotFoundError as exc:
        raise DeployError(f"命令不存在：{argv[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        suffix = f"\n{detail}" if detail else ""
        raise DeployError(
            f"命令执行失败（exit {exc.returncode}）：{' '.join(argv)}{suffix}"
        ) from exc


def _adb_shell_argv(
    serial: str,
    remote_argv: list[str],
    *,
    pty: bool = False,
) -> list[str]:
    """构造不会被设备端 shell 重新拆解参数的 ADB argv。"""
    options = ["-t"] if pty else []
    return [
        "adb", "-s", serial, "shell", *options, shlex.join(remote_argv),
    ]


def check_adb() -> bool:
    """检查宿主机是否安装了 adb。"""
    return shutil.which("adb") is not None


def list_adb_devices() -> dict[str, str]:
    """返回 ADB serial 到状态的映射。"""
    if not check_adb():
        raise DeployError(
            "宿主机未安装 adb，macOS 可执行 "
            "`brew install android-platform-tools`，"
            "Ubuntu/Debian 可执行 `sudo apt install adb`"
        )

    result = _run_checked(["adb", "devices"], capture_output=True)
    devices: dict[str, str] = {}
    for line in result.stdout.splitlines()[1:]:
        fields = line.split()
        if len(fields) >= 2 and not fields[0].startswith("*"):
            devices[fields[0]] = fields[1]
    return devices


def select_adb_device(serial: str | None = None) -> str:
    """选择唯一在线设备，或校验显式 serial。"""
    devices = list_adb_devices()
    if serial:
        state = devices.get(serial)
        if state != "device":
            detail = f"（当前状态：{state}）" if state else "（未发现）"
            raise DeployError(f"ADB 设备 '{serial}' 不可用{detail}")
        return serial

    ready = sorted(key for key, state in devices.items() if state == "device")
    if not ready:
        raise DeployError("未发现状态为 device 的 ADB 设备")
    if len(ready) > 1:
        raise DeployError(
            "发现多台 ADB 设备，请使用 --serial 指定：" + ", ".join(ready)
        )
    return ready[0]


def get_adb_device(serial: str | None = None) -> str:
    """兼容旧调用；新代码应使用 select_adb_device。"""
    return select_adb_device(serial)


def find_latest_deb(
    app_name: str,
    config: dict,
    project_root: Path = PROJECT_ROOT,
) -> Path | None:
    """在仓库统一 target 目录中查找最新的 App deb。"""
    target_dir = _app_output_dir(config, project_root)
    if not target_dir.is_dir():
        return None
    prefix = f"{app_name}_"
    deb_files = [
        path
        for path in target_dir.iterdir()
        if path.is_file()
        and path.name.startswith(prefix)
        and path.name.endswith(".deb")
    ]
    return max(deb_files, key=lambda path: path.stat().st_mtime, default=None)


def _app_output_dir(config: dict, project_root: Path) -> Path:
    return (
        build_dir(project_root)
        / "target"
        / config["board"]
        / config["product"]
        / config["variant"]
        / "app"
    )


def find_latest_debs(
    spec: AppSpec,
    config: dict,
    project_root: Path = PROJECT_ROOT,
) -> list[Path]:
    """返回待部署 deb；vendor 保持声明顺序，lib 只取 runtime。"""
    if spec.build.deb_outputs:
        output_dir = _app_output_dir(config, project_root)
        paths = [output_dir / filename for filename in spec.build.deb_outputs]
        missing = [path.name for path in paths if not path.is_file()]
        if missing:
            raise DeployError(
                f"App '{spec.app.name}' 缺少声明的 .deb 构建产物："
                f"{', '.join(missing)}"
            )
        return paths

    package_name = (
        f"lib{spec.app.name}" if spec.app.type == "lib" else spec.app.name
    )
    filename = (
        f"{package_name}_{spec.app.version}_"
        f"{_map_arch(userspace_arch(config))}.deb"
    )
    output_dir = _app_output_dir(config, project_root)
    if not output_dir.is_dir():
        return []
    exact = next(
        (
            path
            for path in output_dir.iterdir()
            if path.is_file() and path.name == filename
        ),
        None,
    )
    return [exact] if exact is not None else []


def _resolve_app_arg(
    name_or_path: str | Path,
    project_root: Path,
    config: dict,
    caller_cwd: Path | None = None,
) -> tuple[Path, str]:
    """按调用者 cwd 解析路径，纯名称从 project root 的 registry 查找。"""
    raw = str(name_or_path)
    base_dir = Path(caller_cwd or Path.cwd()).expanduser().resolve()
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    is_path = (
        "/" in raw
        or raw.startswith(".")
        or candidate.is_dir()
    )
    if is_path:
        resolved = candidate.resolve()
        if not (resolved.is_dir() and (resolved / "app.yaml").is_file()):
            raise DeployError(f"App 路径 '{raw}' 不存在或缺失 app.yaml")
        return resolved, load_spec(resolved).app.name

    entries = list_all(Path(project_root).resolve(), config)
    app_entry = next((entry for entry in entries if entry.name == raw), None)
    if app_entry is None:
        raise DeployError(f"找不到名为 '{raw}' 的 App")
    return app_entry.source_path.resolve(), app_entry.name


def _load_app(
    name_or_path: str | Path,
    *,
    config: dict | None,
    project_root: Path,
    caller_cwd: Path | None,
) -> tuple[dict, Path, AppSpec]:
    cfg = load_current_config() if config is None else config
    app_dir, _ = _resolve_app_arg(
        name_or_path,
        project_root,
        cfg,
        caller_cwd,
    )
    return cfg, app_dir, load_spec(app_dir)


def _build_app(app_dir: Path, config: dict, project_root: Path) -> None:
    """在最外层 Docker 中构建已在宿主机解析的 App。"""
    root = Path(project_root).resolve()
    resolved = app_dir.resolve()
    volume_arguments = oot_volume_arguments(config)
    try:
        relative = resolved.relative_to(root)
        container_app = CONTAINER_PROJECT_ROOT / relative
    except ValueError:
        mount = f"{resolved}:{resolved}:rw"
        if mount not in volume_arguments:
            volume_arguments.extend(["--volume", mount])
        container_app = resolved

    command = [
        "docker",
        "compose",
        "run",
        "--rm",
        *volume_arguments,
        "build",
        "python3",
        "-m",
        "builder.dev",
        "_build-app",
        str(container_app),
        config["board"],
        config.get("product", "default"),
        config.get("variant", "release"),
    ]
    _run_checked(command, cwd=root)


def _prepare_debs(
    app_dir: Path,
    spec: AppSpec,
    config: dict,
    project_root: Path,
    build_deb: bool,
) -> list[Path]:
    if build_deb:
        print(f"==> 构建 App '{spec.app.name}' ...")
        _build_app(app_dir, config, project_root)

    deb_paths = find_latest_debs(spec, config, project_root)
    if not deb_paths:
        raise DeployError(
            f"未找到 '{spec.app.name}' 的 .deb 构建产物，请先构建该 App"
        )
    print("==> 使用构建产物: " + ", ".join(path.name for path in deb_paths))
    return deb_paths


def _deploy_debs(deb_paths: list[Path], serial: str) -> None:
    """先推送全部 deb，再用一次 dpkg 事务按清单顺序安装。"""
    remote_paths = [f"/tmp/{path.name}" for path in deb_paths]
    pushed: list[str] = []
    try:
        for deb_path, remote_path in zip(deb_paths, remote_paths):
            print(f"==> 推送 {deb_path.name} 到设备 {serial} ...")
            _run_checked(
                ["adb", "-s", serial, "push", str(deb_path), remote_path]
            )
            pushed.append(remote_path)
        _run_checked(
            _adb_shell_argv(serial, ["dpkg", "-i", *remote_paths]),
            capture_output=True,
        )
    finally:
        for remote_path in pushed:
            try:
                subprocess.run(
                    _adb_shell_argv(serial, ["rm", "-f", remote_path]),
                    check=False,
                    capture_output=True,
                    text=True,
                )
            except OSError:
                pass


def _service_unit(spec: AppSpec) -> str:
    if spec.systemd and spec.systemd.unit:
        return Path(spec.systemd.unit).name
    return f"{spec.app.name}.service"


def _executable_path(spec: AppSpec) -> str:
    for source, destination in spec.install.items():
        if source.startswith("bin/") and destination.startswith("/"):
            if destination.endswith("/"):
                return destination + Path(source).name
            return destination
    return f"/usr/bin/{spec.app.name}"


def _validate_runtime(spec: AppSpec, args: list[str]) -> None:
    if spec.app.type not in {"exec", "service"}:
        raise ValueError(
            f"App '{spec.app.name}' 类型为 {spec.app.type!r}，"
            "无法推断默认运行对象"
        )
    if spec.app.type == "service" and args:
        raise ValueError("service App 的默认 run/debug 不接受额外 argv")


def deploy_app(
    name_or_path: str | Path,
    build_deb: bool = True,
    run: bool = False,
    *,
    serial: str | None = None,
    config: dict | None = None,
    project_root: Path = PROJECT_ROOT,
    caller_cwd: Path | None = None,
) -> str:
    """构建（可选）并通过 dpkg 部署 App，返回实际设备 serial。"""
    if run:
        return run_app(
            name_or_path,
            build_deb,
            serial=serial,
            config=config,
            project_root=project_root,
            caller_cwd=caller_cwd,
        )
    cfg, app_dir, spec = _load_app(
        name_or_path,
        config=config,
        project_root=project_root,
        caller_cwd=caller_cwd,
    )
    device = select_adb_device(serial)
    deb_paths = _prepare_debs(app_dir, spec, cfg, project_root, build_deb)
    _deploy_debs(deb_paths, device)
    print(f"App '{spec.app.name}' 已部署到 {device}")
    return device


def run_app(
    name_or_path: str | Path,
    build_deb: bool = True,
    *,
    serial: str | None = None,
    args: list[str] | None = None,
    config: dict | None = None,
    project_root: Path = PROJECT_ROOT,
    caller_cwd: Path | None = None,
) -> str:
    """构建、部署并运行 exec/service App。"""
    cfg, app_dir, spec = _load_app(
        name_or_path,
        config=config,
        project_root=project_root,
        caller_cwd=caller_cwd,
    )
    extra_args = list(args or [])
    _validate_runtime(spec, extra_args)
    device = select_adb_device(serial)
    deb_paths = _prepare_debs(app_dir, spec, cfg, project_root, build_deb)
    _deploy_debs(deb_paths, device)

    if spec.app.type == "exec":
        _run_checked(
            _adb_shell_argv(device, [
                _executable_path(spec),
                *extra_args,
            ])
        )
    else:
        unit = _service_unit(spec)
        _run_checked(
            _adb_shell_argv(device, ["systemctl", "daemon-reload"])
        )
        _run_checked(
            _adb_shell_argv(device, ["systemctl", "restart", unit])
        )
        _run_checked(
            _adb_shell_argv(device, [
                "systemctl",
                "status",
                unit,
                "--no-pager",
            ])
        )
    return device


def log_app(
    name_or_path: str | Path,
    *,
    serial: str | None = None,
    follow: bool = True,
    lines: int | None = None,
    since: str | None = None,
    config: dict | None = None,
    project_root: Path = PROJECT_ROOT,
    caller_cwd: Path | None = None,
) -> str:
    """读取 service App 的 journal，默认持续跟随。"""
    _, _, spec = _load_app(
        name_or_path,
        config=config,
        project_root=project_root,
        caller_cwd=caller_cwd,
    )
    if spec.app.type != "service":
        raise ValueError(
            f"App '{spec.app.name}' 类型为 {spec.app.type!r}，"
            "无法推断默认日志源"
        )
    if lines is not None and lines < 0:
        raise ValueError("日志行数不得为负数")
    device = select_adb_device(serial)
    remote_command = [
        "journalctl",
        "-u",
        _service_unit(spec),
        "--no-pager",
    ]
    if lines is not None:
        remote_command.extend(["-n", str(lines)])
    if since is not None:
        remote_command.extend(["--since", since])
    if follow:
        remote_command.append("-f")
    _run_checked(_adb_shell_argv(device, remote_command))
    return device


def debug_app(
    name_or_path: str | Path,
    *,
    serial: str | None = None,
    args: list[str] | None = None,
    config: dict | None = None,
    project_root: Path = PROJECT_ROOT,
    caller_cwd: Path | None = None,
) -> str:
    """在 debug target 上用目标机 GDB 启动或 attach App。"""
    cfg, _, spec = _load_app(
        name_or_path,
        config=config,
        project_root=project_root,
        caller_cwd=caller_cwd,
    )
    extra_args = list(args or [])
    _validate_runtime(spec, extra_args)
    if cfg.get("variant") != "debug":
        raise ValueError(
            "默认 GDB 调试仅支持 debug variant，"
            f"当前为 {cfg.get('variant')!r}；"
            "请先选择 debug target 或声明显式 debug action"
        )
    device = select_adb_device(serial)

    if spec.app.type == "exec":
        _run_checked(
            _adb_shell_argv(
                device,
                ["gdb", "--args", _executable_path(spec), *extra_args],
                pty=True,
            )
        )
        return device

    unit = _service_unit(spec)
    result = _run_checked(
        _adb_shell_argv(device, [
            "systemctl",
            "show",
            unit,
            "--property",
            "MainPID",
            "--value",
        ]),
        capture_output=True,
    )
    pid = result.stdout.strip()
    if not pid.isdecimal() or int(pid) <= 0:
        raise DeployError(f"service {unit} 当前没有可 attach 的 MainPID")
    _run_checked(_adb_shell_argv(device, ["gdb", "-p", pid], pty=True))
    return device


def main(argv: list[str] | None = None) -> int:
    """兼容旧的 ``python -m builder.deploy`` 入口。"""
    parser = argparse.ArgumentParser(description="flange 单 App 热部署工具")
    parser.add_argument("app", help="App 名称或宿主机目录路径")
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="跳过构建步骤，直接推送现有的 .deb",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="部署完成后立即运行 exec 或重启 service",
    )
    parser.add_argument("--serial", help="目标 ADB 设备 serial")
    parsed = parser.parse_args(argv)

    try:
        if parsed.run:
            run_app(
                parsed.app,
                build_deb=not parsed.no_build,
                serial=parsed.serial,
            )
        else:
            deploy_app(
                parsed.app,
                build_deb=not parsed.no_build,
                serial=parsed.serial,
            )
    except (DeployError, ValueError, FileNotFoundError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n已停止。", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
