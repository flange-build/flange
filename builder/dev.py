"""App 与 Package 的资源优先开发命令。"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from builder.app_spec import AppSpec, load_spec
from builder.config.canonical import userspace_arch
from builder.config.loader import load_current_config
from builder.docker import BuildError, DockerRunner
from builder.oot_mounts import _mount_root
from builder.paths import PROJECT_ROOT, build_dir
from builder.scaffold import AppScaffold, PackageScaffold
from builder.source import SourceManager

_CONTAINER_ROOT = Path("/workspace")
_DEVICE_ACTIONS = {"deploy", "run", "debug", "log"}


class DevelopmentError(RuntimeError):
    """资源开发命令无法安全继续。"""


def _load_target_config() -> dict:
    try:
        return load_current_config()
    except FileNotFoundError as exc:
        raise DevelopmentError("未选择目标配置，请先执行 lunch") from exc


def resolve_app_dir(
    name_or_path: str | None,
    config: dict,
    *,
    caller_cwd: Path | None = None,
    project_root: Path = PROJECT_ROOT,
) -> Path:
    """按调用者 cwd 解析路径，否则复用 App registry 名称查找。"""
    target = name_or_path or "."
    cwd = Path(caller_cwd or Path.cwd())
    candidate = Path(target).expanduser()
    if not candidate.is_absolute():
        candidate = cwd / candidate
    explicit_path = (
        "/" in target
        or target.startswith(".")
        or candidate.is_dir()
    )
    if explicit_path:
        resolved = candidate.resolve()
        if not resolved.is_dir() or not (resolved / "app.yaml").is_file():
            raise DevelopmentError(
                f"App 路径不存在或缺少 app.yaml：{resolved}"
            )
        return resolved

    source = SourceManager(
        sources_dir=build_dir(project_root) / "sources",
        project_root=project_root,
    )
    return source.ensure_app(target, config).resolve()


def _container_location(
    path: Path,
    *,
    mount_root: Path | None = None,
) -> tuple[Path, list[Path]]:
    """返回容器内路径与最外层 Docker 所需挂载。"""
    resolved = path.resolve()
    root = PROJECT_ROOT.resolve()
    try:
        return _CONTAINER_ROOT / resolved.relative_to(root), []
    except ValueError:
        return resolved, [_mount_root((mount_root or resolved).resolve())]


def _target_env(
    config: dict,
    source_dir: Path,
    *,
    project_root: Path,
    serial: str | None = None,
    component: str | None = None,
) -> dict[str, str]:
    """构造 action 可依赖的最小稳定环境。"""
    target_dir = (
        build_dir(project_root)
        / "target"
        / config["board"]
        / config.get("product", "default")
        / config.get("variant", "release")
    )
    env = {
        "FLANGE_PROJECT_ROOT": str(project_root),
        "FLANGE_SOURCE_DIR": str(source_dir),
        "FLANGE_TARGET_DIR": str(target_dir),
        "FLANGE_BOARD": str(config["board"]),
        "FLANGE_PRODUCT": str(config.get("product", "default")),
        "FLANGE_VARIANT": str(config.get("variant", "release")),
        "FLANGE_TARGET_ARCH": userspace_arch(config),
    }
    if serial:
        env["FLANGE_ADB_SERIAL"] = serial
    if component:
        env["FLANGE_COMPONENT"] = component
    return env


def _run_action(
    command: Sequence[str],
    action_args: Sequence[str],
    source_dir: Path,
    config: dict,
    *,
    in_container: bool,
    serial: str | None = None,
    component: str | None = None,
    mount_root: Path | None = None,
) -> None:
    """不经 shell 执行一个已校验的 argv action。"""
    argv = [*command, *action_args]
    if in_container:
        container_dir, mounts = _container_location(
            source_dir,
            mount_root=mount_root,
        )
        env = _target_env(
            config,
            container_dir,
            project_root=_CONTAINER_ROOT,
            serial=serial,
            component=component,
        )
        print(f"==> Docker action: {shlex.join(argv)}")
        DockerRunner(project_dir=PROJECT_ROOT).run(
            argv,
            cwd=str(container_dir),
            env=env,
            extra_mounts=mounts,
        )
        return

    env = {
        **os.environ,
        **_target_env(
            config,
            source_dir,
            project_root=PROJECT_ROOT,
            serial=serial,
            component=component,
        ),
    }
    print(f"==> Host action: {shlex.join(argv)}")
    subprocess.run(argv, cwd=source_dir, env=env, check=True)


def _build_standard_app(
    app_dir: Path,
    config: dict,
    *,
    mount_root: Path | None = None,
) -> None:
    """在最外层 Docker 挂载完成后调用既有 AppBuilder。"""
    container_dir, mounts = _container_location(
        app_dir,
        mount_root=mount_root,
    )
    DockerRunner(project_dir=PROJECT_ROOT).run(
        [
            "python3", "-m", "builder.dev", "_build-app",
            str(container_dir),
            config["board"],
            config.get("product", "default"),
            config.get("variant", "release"),
        ],
        extra_mounts=mounts,
    )


def _build_app(
    app_dir: Path,
    spec: AppSpec,
    config: dict,
    action_args: Sequence[str],
    *,
    mount_root: Path | None = None,
) -> None:
    action = spec.actions.get("build")
    if action:
        _run_action(
            action,
            action_args,
            app_dir,
            config,
            in_container=True,
            mount_root=mount_root,
        )
    elif action_args:
        raise DevelopmentError("标准 App build 不接受 `--` 透传参数")
    else:
        _build_standard_app(app_dir, config, mount_root=mount_root)


def _deploy_standard_app(app_dir: Path, config: dict, serial: str | None) -> str:
    from builder.deploy import deploy_app

    return deploy_app(
        str(app_dir),
        build_deb=False,
        run=False,
        serial=serial,
        project_root=PROJECT_ROOT,
        config=config,
    )


def _app_lifecycle(
    action: str,
    app_dir: Path,
    config: dict,
    *,
    action_args: Sequence[str] = (),
    serial: str | None = None,
    no_build: bool = False,
    lines: int | None = None,
    since: str | None = None,
    follow: bool = True,
    build_mount_root: Path | None = None,
) -> None:
    """运行单个 App 生命周期；显式 action 覆盖同名默认行为。"""
    spec = load_spec(app_dir)
    explicit = spec.actions.get(action)
    if explicit:
        if action in _DEVICE_ACTIONS:
            from builder.deploy import select_adb_device

            serial = select_adb_device(serial)
        _run_action(
            explicit,
            action_args,
            app_dir,
            config,
            in_container=action == "build",
            serial=serial,
            mount_root=build_mount_root,
        )
        return

    if action == "build":
        _build_app(
            app_dir,
            spec,
            config,
            action_args,
            mount_root=build_mount_root,
        )
        return
    if action == "log":
        if action_args:
            raise DevelopmentError("标准 App log 不接受 `--` 透传参数")
        from builder.deploy import log_app

        log_app(
            app_dir,
            serial=serial,
            lines=lines,
            since=since,
            follow=follow,
            config=config,
            project_root=PROJECT_ROOT,
        )
        return

    if action == "deploy" and action_args:
        raise DevelopmentError("标准 App deploy 不接受 `--` 透传参数")
    if action == "deploy" and spec.app.type in {"amp", "staging"}:
        raise DevelopmentError(
            f"App 类型 {spec.app.type!r} 不产出可部署 deb；请声明显式 deploy action"
        )
    if action in {"run", "debug"}:
        if spec.app.type not in {"exec", "service"}:
            raise DevelopmentError(
                f"App 类型 {spec.app.type!r} 不支持默认 {action}；请声明显式 action"
            )
        if spec.app.type == "service" and action_args:
            raise DevelopmentError("service App 不接受 `--` 运行参数")
    if action == "debug" and config.get("variant") != "debug":
        raise DevelopmentError(
            "默认 GDB 调试仅支持 debug variant；请先 lunch debug target，"
            "或声明显式 debug action"
        )
    if not no_build:
        _build_app(
            app_dir,
            spec,
            config,
            (),
            mount_root=build_mount_root,
        )

    if action == "deploy":
        _deploy_standard_app(app_dir, config, serial)
        return
    if action == "run":
        from builder.deploy import run_app

        run_app(
            app_dir,
            build_deb=False,
            serial=serial,
            args=list(action_args),
            config=config,
            project_root=PROJECT_ROOT,
        )
        return
    if action == "debug":
        from builder.deploy import debug_app

        device = _deploy_standard_app(app_dir, config, serial)
        debug_app(
            app_dir,
            config=config,
            serial=device,
            args=list(action_args),
        )
        return
    raise DevelopmentError(f"未知 App action：{action}")


def _vendor_components(
    package: dict,
    package_dir: Path,
    variant: str,
    selected: str | None,
) -> list[tuple[str, Path]]:
    """返回当前 variant 可用的 vendor component。"""
    vendors: list[tuple[str, Path]] = []
    for component in package["components"]:
        if component["type"] != "vendor":
            continue
        variants = component.get("variants")
        if variants and variant not in variants:
            continue
        name = component["name"]
        if selected and name != selected:
            continue
        app_dir = (package_dir / component["dir"]).resolve()
        if not (app_dir / "app.yaml").is_file():
            raise DevelopmentError(
                f"Package vendor component {name!r} 缺少 app.yaml：{app_dir}"
            )
        vendors.append((name, app_dir))

    if selected and not vendors:
        choices = ", ".join(
            component.get("name", "?")
            for component in package["components"]
            if component.get("type") == "vendor"
        ) or "无"
        raise DevelopmentError(
            f"找不到 vendor component {selected!r}；可选：{choices}"
        )
    return vendors


def _package_lifecycle(
    action: str,
    package_dir: Path,
    package: dict,
    config: dict,
    *,
    action_args: Sequence[str] = (),
    component: str | None = None,
    serial: str | None = None,
    no_build: bool = False,
    lines: int | None = None,
    since: str | None = None,
    follow: bool = True,
) -> None:
    """执行 Package action，或委托给既有 vendor App 生命周期。"""
    explicit = package.get("actions", {}).get(action)
    if explicit:
        if action in _DEVICE_ACTIONS:
            from builder.deploy import select_adb_device

            serial = select_adb_device(serial)
        _run_action(
            explicit,
            action_args,
            package_dir,
            config,
            in_container=action == "build",
            serial=serial,
            component=component,
        )
        return

    if component is None:
        variant = config.get("variant", "release")
        unsupported = [
            f"{item.get('name', '?')} ({item['type']})"
            for item in package["components"]
            if item["type"] != "vendor"
            and (not item.get("variants") or variant in item["variants"])
        ]
        if unsupported:
            raise DevelopmentError(
                f"Package {action} 无法安全处理 component："
                f"{', '.join(unsupported)}；请声明显式 action，"
                "或用 --component 选择 vendor component"
            )

    vendors = _vendor_components(
        package,
        package_dir,
        config.get("variant", "release"),
        component,
    )
    if not vendors:
        kinds = sorted({item["type"] for item in package["components"]})
        raise DevelopmentError(
            f"Package 不含可复用的 vendor component（现有类型："
            f"{', '.join(kinds) or '无'}）；请在 PACKAGE['actions'] 中定义 "
            f"{action!r} argv"
        )

    if action in {"run", "debug", "log"} and len(vendors) != 1:
        choices = ", ".join(name for name, _ in vendors)
        raise DevelopmentError(
            f"Package 有多个可运行 component，请用 --component 选择：{choices}"
        )

    if action == "deploy":
        if action_args:
            raise DevelopmentError("标准 Package deploy 不接受 `--` 透传参数")
        specs = [(name, app_dir, load_spec(app_dir)) for name, app_dir in vendors]
        if not any(
            spec.app.type not in {"amp", "staging"}
            for _, _, spec in specs
        ):
            raise DevelopmentError(
                "Package 不含可部署 deb 的 vendor component；"
                "请声明显式 deploy action"
            )
        for name, app_dir, spec in specs:
            if spec.app.type in {"amp", "staging"}:
                if not no_build:
                    _app_lifecycle(
                        "build",
                        app_dir,
                        config,
                        build_mount_root=package_dir,
                    )
                print(
                    f"==> 跳过 {name} 的设备安装："
                    f"{spec.app.type} App 不产出 deb"
                )
                continue
            _app_lifecycle(
                action,
                app_dir,
                config,
                serial=serial,
                no_build=no_build,
                build_mount_root=package_dir,
            )
        return

    for _, app_dir in vendors:
        _app_lifecycle(
            action,
            app_dir,
            config,
            action_args=action_args,
            serial=serial,
            no_build=no_build,
            lines=lines,
            since=since,
            follow=follow,
            build_mount_root=package_dir,
        )


def _add_create_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("name", help="资源名称")
    parser.add_argument("--dir", type=Path, help="父目录，默认调用者当前目录")
    parser.add_argument(
        "--type",
        default="exec",
        choices=("exec", "service", "lib", "test", "amp"),
        help="内嵌 App 类型（默认 exec）",
    )
    parser.add_argument(
        "--build-system",
        default="cmake",
        choices=("none", "cmake", "meson", "make", "swift", "amp", "scons"),
        help="构建系统（默认 cmake）",
    )
    parser.add_argument("--version", default="0.1.0", help="初始版本")
    parser.add_argument("--description", default="", help="中文描述")
    parser.add_argument(
        "--embedded-swift",
        action="store_true",
        help="App amp+scons 的 Embedded Swift 骨架",
    )


def _add_lifecycle_parsers(
    resource: argparse.ArgumentParser,
    *,
    package: bool,
) -> None:
    actions = resource.add_subparsers(dest="action", required=True)
    create = actions.add_parser("create", help="在当前目录创建脚手架")
    _add_create_parser(create)

    for name in ("build", "deploy", "run", "debug", "log"):
        action = actions.add_parser(
            name,
            help=f"{name} 目标资源",
            epilog=(
                "使用 `--` 分隔后续 argv；仅显式 action 与 exec run/debug "
                "接受透传参数。"
            ),
        )
        action.add_argument(
            "target",
            nargs="?",
            default=".",
            help="仓库内名称或目录路径（默认当前目录）",
        )
        if package:
            action.add_argument("--component", help="选择 vendor component")
        if name in _DEVICE_ACTIONS:
            action.add_argument("--serial", help="ADB device serial")
        if name in {"deploy", "run", "debug"}:
            action.add_argument(
                "--no-build", action="store_true", help="复用已有构建产物"
            )
        if name == "log":
            action.add_argument("--lines", type=int, help="显示末尾日志行数")
            action.add_argument("--since", help="journalctl --since 值")
            action.add_argument(
                "--no-follow", action="store_true", help="输出后立即退出"
            )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flange",
        description="在任意目录开发 flange App 与 Package",
        epilog="在 `--` 后追加的参数会原样传给显式 action 或 exec run/debug。",
    )
    resources = parser.add_subparsers(dest="resource", required=True)
    app = resources.add_parser("app", help="App 开发生命周期")
    package = resources.add_parser("package", help="Package 开发生命周期")
    _add_lifecycle_parsers(app, package=False)
    _add_lifecycle_parsers(package, package=True)
    return parser


def _split_action_args(argv: Sequence[str]) -> tuple[list[str], list[str]]:
    values = list(argv)
    if "--" not in values:
        return values, []
    index = values.index("--")
    return values[:index], values[index + 1:]


def _internal_build_app(argv: Sequence[str]) -> int:
    if len(argv) != 4:
        raise DevelopmentError(
            "内部 build-app 需要 App 路径与 board/product/variant"
        )
    from builder.app import AppBuilder
    from builder.cache import BuildCache
    from builder.config.registry import resolve_config
    from builder.config.validate import validate_config

    app_path, board, product, variant = argv
    config = resolve_config(board, product, variant)
    validate_config(config)
    source = SourceManager(
        sources_dir=build_dir(PROJECT_ROOT) / "sources",
        project_root=PROJECT_ROOT,
    )
    builder = AppBuilder(
        DockerRunner(project_dir=PROJECT_ROOT), source, config
    )
    builder.cache = BuildCache(config, project_root=PROJECT_ROOT)
    builder.build_one(app_path)
    return 0


def _create(args: argparse.Namespace) -> None:
    parent = (args.dir or Path.cwd()).expanduser().resolve()
    if args.resource == "app":
        AppScaffold(PROJECT_ROOT).create(
            args.name,
            args.type,
            args.build_system,
            parent_dir=parent,
            version=args.version,
            description=args.description,
            embedded_swift=args.embedded_swift,
        )
        return
    if args.embedded_swift:
        raise DevelopmentError("Package scaffold 暂不支持 --embedded-swift")
    PackageScaffold(PROJECT_ROOT).create(
        args.name,
        parent_dir=parent,
        app_type=args.type,
        build_system=args.build_system,
        version=args.version,
        description=args.description,
    )


def _run(args: argparse.Namespace, action_args: Sequence[str]) -> None:
    if args.action == "create":
        if action_args:
            raise DevelopmentError("create 不接受 `--` 透传参数")
        _create(args)
        return

    config = _load_target_config()
    options = {
        "action_args": action_args,
        "serial": getattr(args, "serial", None),
        "no_build": getattr(args, "no_build", False),
        "lines": getattr(args, "lines", None),
        "since": getattr(args, "since", None),
        "follow": not getattr(args, "no_follow", False),
    }
    if args.resource == "app":
        app_dir = resolve_app_dir(args.target, config)
        _app_lifecycle(args.action, app_dir, config, **options)
        return

    from builder.packages import load_package_manifest_dir, resolve_package_dir

    package_dir = resolve_package_dir(
        args.target,
        project_root=PROJECT_ROOT,
        caller_cwd=Path.cwd(),
    )
    package = load_package_manifest_dir(package_dir)
    _package_lifecycle(
        args.action,
        package_dir,
        package,
        config,
        component=getattr(args, "component", None),
        **options,
    )


def main(argv: Sequence[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    try:
        if values[:1] == ["_build-app"]:
            return _internal_build_app(values[1:])
        command_args, action_args = _split_action_args(values)
        args = _parser().parse_args(command_args)
        _run(args, action_args)
        return 0
    except (ValueError, FileNotFoundError, RuntimeError, BuildError) as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"[错误] 命令失败（exit {exc.returncode}）：{exc.cmd}", file=sys.stderr)
        return exc.returncode or 1
    except KeyboardInterrupt:
        print("\n已停止。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
