"""资源优先开发编排；工作区、构建计划与设备结果共享显式上下文。"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import uuid
from dataclasses import asdict, replace
from pathlib import Path
from typing import Sequence

from builder.app import AppBuilder
from builder.app_model import AppBuildReport
from builder.app_resolver import AppResolver
from builder.app_spec import SUPPORTED_APP_ARCHITECTURES, load_spec
from builder.artifacts import ArtifactManifest
from builder.build_result import BuildFailure, run_build_container, write_failure
from builder.config.canonical import userspace_arch
from builder.deploy import DeviceSession, operate_report
from builder.development_output import run_logged
from builder.docker import BuildError, DockerRunner
from builder.locking import FileLock, atomic_write
from builder.paths import PROJECT_ROOT
from builder.presentation import ArgumentParser, Presenter
from builder.scaffold import AppScaffold, PackageScaffold
from builder.source import SourceManager
from builder.workspace import Target, WorkspaceContext, load_workspace, resolve_config


class DevelopmentError(RuntimeError):
    """资源请求缺少可执行的生命周期契约。"""


def _builder(context: WorkspaceContext, config: dict) -> AppBuilder:
    from builder.config.jsonnet import ResolvedConfig
    config = ResolvedConfig(config)
    config.layer_stack = context.layer_stack
    return AppBuilder(
        DockerRunner(context=context, config=config), SourceManager(context=context), config, context=context
    )


def _context_payload(context: WorkspaceContext) -> dict:
    return {
        "tool_root": str(context.tool_root),
        "workspace_root": str(context.workspace_root),
        "build_root": str(context.build_root),
        "target": asdict(context.target),
        "invocation_dir": str(context.invocation_dir),
        "apps": {name: str(path) for name, path in context.apps.items()},
        "app_dirs": [str(path) for path in context.app_dirs],
        "layers": context.layer_stack.to_dict(),
    }


def _context_from_payload(value: dict) -> WorkspaceContext:
    from builder.layers import Layer, LayerStack, ProviderRef
    layers = value.get("layers")
    stack = LayerStack(tuple(Layer(item["name"], Path(item["root"]),
        tuple(item["requires"]), tuple(ProviderRef(**provider) for provider in item["providers"]))
        for item in layers)) if layers else LayerStack.base(Path(value["tool_root"]))
    return WorkspaceContext(
        tool_root=Path(value["tool_root"]),
        workspace_root=Path(value["workspace_root"]),
        build_root=Path(value["build_root"]),
        target=Target(**value["target"]),
        invocation_dir=Path(value["invocation_dir"]),
        apps={name: Path(path) for name, path in value["apps"].items()},
        app_dirs=tuple(Path(path) for path in value["app_dirs"]),
        layer_stack=stack,
    )


def build_report(
    context: WorkspaceContext,
    requests: Sequence[str | Path],
    *,
    force=False,
    no_build=False,
    config: dict | None = None,
    output_level="normal",
) -> AppBuildReport:
    """宿主解析全部依赖并挂载，再把同一请求上下文交给构建容器。"""
    config = resolve_config(context) if config is None else config
    from builder.build_environment import resolve_environment
    if no_build and (config.get("userland_toolchain") or resolve_environment(config, context) is not None):
        runner = DockerRunner(context=context, config=config)
        context.environment_ids[runner.environment_name] = runner.environment_identity()
    builder = _builder(context, config)
    if no_build:
        return builder.existing(requests)
    roots, resources = builder.resolver.closure(requests)
    # Docker Desktop 的 bind mount 元数据可能短时落后于宿主 chmod。
    # 宿主已经发现的损坏必须进入执行请求，不能被容器的旧视图误判为命中。
    with FileLock(context.build_root / "locks" / f"{context.target.key}.lock"):
        for resource in resources:
            directory = context.target_dir / "apps" / resource.resource_id
            if directory.exists():
                manifest = ArtifactManifest.load(directory / "manifest.json")
                if manifest is None or not manifest.validate():
                    force = True
    # 明确冻结解析结果，容器内不再 fetch 分支或根据另一份 cwd 选择来源。
    frozen = replace(
        context,
        apps={**context.apps, **{item.spec.app.name: item.source_dir for item in resources}},
    )
    by_id = {item.resource_id: item for item in resources}
    resolved_requests = [str(by_id[key].source_dir) for key in roots]
    request_path = context.build_root / "requests" / f"app-{uuid.uuid4().hex}.json"
    result_path = request_path.with_suffix(".result.json")
    payload = {
        "context": _context_payload(frozen),
        "config": config,
        "requests": resolved_requests,
        "force": force,
        "result_path": str(result_path),
        "output_level": output_level,
    }
    atomic_write(request_path, json.dumps(payload, ensure_ascii=False))
    try:
        mounts = list(dict.fromkeys(builder._source_root(item.source_dir) for item in resources))
        run_build_container(
            DockerRunner(context=context),
            ["python3", "-m", "builder.dev", "_build-app", str(request_path)],
            extra_mounts=mounts,
        )
        return AppBuildReport.load(result_path)
    finally:
        request_path.unlink(missing_ok=True)
        result_path.unlink(missing_ok=True)


def _internal_build(request_path: Path) -> dict:
    request = json.loads(request_path.read_text())
    context = _context_from_payload(request["context"])

    def execute(output):
        builder = _builder(context, request["config"])
        builder.output = output
        builder._docker.output = output
        builder._source.output = output
        return builder.build(request["requests"], force=request["force"])

    report = run_logged(
        context, request["config"], "app", request.get("output_level", "normal"), execute,
        retry_command=shlex.join([
            "flange", "-C", str(context.workspace_root), "--target", context.target.key,
            "app", "build", *request["requests"],
        ]),
    )
    if request.get("result_path"):
        report.write(Path(request["result_path"]))
    return report_data(report)


def _package_build_report(
    context, config, directory, package, *, force=False, no_build=False, output_level="normal"
):
    from builder.package_build import PackageBuilder

    if no_build:
        return PackageBuilder(context, DockerRunner(context=context)).build(
            directory, package, no_build=True
        )
    request_path = context.build_root / "requests" / f"package-{uuid.uuid4().hex}.json"
    result_path = request_path.with_suffix(".result.json")
    atomic_write(
        request_path,
        json.dumps(
            {
                "context": _context_payload(context),
                "config": config,
                "directory": str(directory),
                "package": package,
                "force": force,
                "output_level": output_level,
                "result_path": str(result_path),
            },
            ensure_ascii=False,
        ),
    )
    try:
        run_build_container(
            DockerRunner(context=context),
            ["python3", "-m", "builder.dev", "_build-package", str(request_path)],
            extra_mounts=[directory],
        )
        manifest = ArtifactManifest.from_dict(json.loads(result_path.read_text()))
        if not manifest.validate():
            raise DevelopmentError("Package 宿主产物校验失败，请重新构建")
        return manifest
    finally:
        request_path.unlink(missing_ok=True)
        result_path.unlink(missing_ok=True)


def _internal_package_build(request_path):
    from builder.package_build import PackageBuilder

    request = json.loads(Path(request_path).read_text())
    context = _context_from_payload(request["context"])

    def execute(output):
        docker = DockerRunner(context=context, output=output)
        output.status(f"构建 Package {request['package']['name']}")
        return PackageBuilder(context, docker).build(
            Path(request["directory"]), request["package"], force=request["force"]
        )

    manifest = run_logged(
        context, request["config"], "package", request["output_level"], execute,
        retry_command=shlex.join([
            "flange", "-C", str(context.workspace_root), "--target", context.target.key,
            "package", "build", request["directory"],
        ]),
    )
    atomic_write(Path(request["result_path"]), json.dumps(manifest.to_dict(), ensure_ascii=False))
    return {"identity": manifest.identity}


def _output_level(args):
    return (
        "verbose"
        if getattr(args, "verbose", False)
        else "quiet"
        if getattr(args, "quiet", False)
        else "normal"
    )


def report_data(report: AppBuildReport) -> dict:
    return {
        "target": report.target,
        "architecture": report.architecture,
        "identity": report.identity,
        "roots": list(report.roots),
        "apps": [
            {
                "name": item.name,
                "resource_id": item.resource_id,
                "reused": item.reused,
                "source_dir": str(item.source_dir),
                "manifest_path": str(item.manifest_path),
                "packages": [package.to_dict() for package in item.packages],
                "runtime_debs": [str(path) for path in item.runtime_debs],
            }
            for item in report.ordered
        ],
    }


def _action(
    command: Sequence[str],
    args: Sequence[str],
    source: Path,
    context: WorkspaceContext,
    report: AppBuildReport | ArtifactManifest,
    action: str,
    serial: str | None,
    timeout: int,
) -> dict:
    with FileLock(context.build_root / "locks" / f"{context.target.key}.lock"):
        if not report.validate():
            raise DevelopmentError("显式动作引用的产物校验失败，请重新构建")
        return _execute_action(command, args, source, context, report, action, serial, timeout)


def _execute_action(
    command: Sequence[str],
    args: Sequence[str],
    source: Path,
    context: WorkspaceContext,
    report: AppBuildReport | ArtifactManifest,
    action: str,
    serial: str | None,
    timeout: int,
) -> dict:
    """显式动作保持 argv 边界，并把自定义测试也纳入产物关联会话。"""
    session = DeviceSession(context, report, action, serial or "")
    session.data["device"]["transport"] = "action"
    session.data["command"] = [*command, *args]
    env = {
        **os.environ,
        "FLANGE_SOURCE_DIR": str(source),
        "FLANGE_PROJECT_ROOT": str(context.tool_root),
        "FLANGE_TARGET_DIR": str(context.target_dir),
        "FLANGE_BUILD_ROOT": str(context.build_root),
        "FLANGE_ADB_SERIAL": serial or "",
        "FLANGE_BOARD": context.target.board,
        "FLANGE_PRODUCT": context.target.product,
        "FLANGE_VARIANT": context.target.variant,
        "FLANGE_ARTIFACT_IDENTITY": report.identity,
    }
    if isinstance(report, ArtifactManifest):
        artifact_dir = next(item.path for item in report.artifacts if item.name == "artifacts")
        env.update(FLANGE_TARGET_DIR=str(artifact_dir), FLANGE_PACKAGE_OUTPUT_DIR=str(artifact_dir))
    try:
        result = subprocess.run(
            [*command, *args],
            cwd=source,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout if action == "test" else None,
        )
        stdout_path, stderr_path = (
            session.directory / "stdout.log",
            session.directory / "stderr.log",
        )
        stdout_path.write_text(result.stdout or "")
        stderr_path.write_text(result.stderr or "")
        session.data.update(
            stdout=result.stdout,
            stderr=result.stderr,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
        )
        return session.finish(
            "succeeded" if result.returncode == 0 else "failed", exit_code=result.returncode
        )
    except subprocess.TimeoutExpired as exc:

        def decoded(value):
            return value.decode(errors="replace") if isinstance(value, bytes) else (value or "")

        stdout_path, stderr_path = (
            session.directory / "stdout.log",
            session.directory / "stderr.log",
        )
        stdout_path.write_text(decoded(exc.stdout))
        stderr_path.write_text(decoded(exc.stderr))
        session.data.update(
            stdout=decoded(exc.stdout),
            stderr=decoded(exc.stderr),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
        )
        return session.finish("timed_out", exit_code=124, error=exc)
    except KeyboardInterrupt:
        session.finish("interrupted", exit_code=130)
        raise
    except BaseException as exc:
        session.finish("failed", exit_code=1, error=exc)
        raise


def _app_request(args, forwarded: Sequence[str], context: WorkspaceContext, config: dict) -> dict:
    builder = _builder(context, config)
    if args.action == "plan":
        return {"plans": [plan.to_dict() for plan in builder.plan([args.target])]}
    resolver = (
        AppResolver(context, builder._source, config, read_only=True)
        if getattr(args, "no_build", False) or args.action == "log"
        else builder.resolver
    )
    path = resolver.resolve(args.target)
    spec = load_spec(path, layer_stack=context.layer_stack)
    if args.action == "build" and forwarded:
        raise DevelopmentError("build 的配置由 AppSpec 描述，不接受额外 argv")
    if args.action == "deploy" and forwarded and "deploy" not in spec.actions:
        raise DevelopmentError("默认 deploy 不接受额外 argv")
    if args.action == "debug" and "debug" not in spec.actions and context.target.variant != "debug":
        raise DevelopmentError("默认 GDB 调试需要 debug target")
    if (
        args.action == "debug"
        and "debug" not in spec.actions
        and os.environ.get("FLANGE_NO_INTERACTION") == "1"
    ):
        raise DevelopmentError(
            "GDB 需要交互终端；请取消 FLANGE_NO_INTERACTION 后在终端执行 app debug"
        )
    report = build_report(
        context,
        [str(path)],
        config=config,
        force=getattr(args, "force", False),
        output_level=_output_level(args),
        no_build=getattr(args, "no_build", False) or args.action == "log",
    )
    if args.action == "build":
        return {**report_data(report), "build_log": str(context.target_dir / "build.log")}
    explicit = spec.actions.get(args.action)
    if explicit:
        return _action(
            explicit,
            forwarded,
            path,
            context,
            report,
            args.action,
            getattr(args, "serial", None),
            getattr(args, "timeout", 60),
        )
    return operate_report(
        context,
        report,
        args.action,
        serial=getattr(args, "serial", None),
        args=forwarded,
        lines=getattr(args, "lines", None),
        since=getattr(args, "since", None),
        follow=not getattr(args, "no_follow", False),
        timeout=getattr(args, "timeout", 60),
        debug_mode=getattr(args, "mode", "target"),
        port=getattr(args, "port", 2345),
    )


def _package_request(
    args, forwarded: Sequence[str], context: WorkspaceContext, config: dict
) -> dict:
    from builder.packages import load_package_manifest_dir, resolve_package_dir

    directory = resolve_package_dir(
        args.target, project_root=context.tool_root, caller_cwd=context.invocation_dir,
        layer_stack=context.layer_stack,
    )
    package = load_package_manifest_dir(directory)
    actions = package.get("actions", {})
    if "build" in actions:
        from builder.package_build import PackageBuilder

        builder = PackageBuilder(context, DockerRunner(context=context))
        if args.component:
            raise DevelopmentError("Package 显式构建动作描述完整交付，不接受 --component")
        if args.action == "plan":
            return {"plans": [builder.plan(directory, package).to_dict()]}
        if args.action == "build" and forwarded:
            raise DevelopmentError("Package 构建参数由 actions.build 描述，不接受额外 argv")
        if args.action != "build" and args.action not in actions:
            raise DevelopmentError(f"该 Package 必须声明 actions.{args.action} 才能消费自定义产物")
        manifest = _package_build_report(
            context,
            config,
            directory,
            package,
            force=getattr(args, "force", False),
            output_level=_output_level(args),
            no_build=getattr(args, "no_build", False) or args.action == "log",
        )
        if args.action == "build":
            return {
                "package": package["name"],
                "identity": manifest.identity,
                "manifest_path": str(manifest.artifacts[0].path.parent / "manifest.json"),
                "build_log": str(context.target_dir / "build.log"),
                "artifacts": [str(item.path) for item in manifest.artifacts],
            }
        return _action(
            actions[args.action],
            forwarded,
            directory,
            context,
            manifest,
            args.action,
            getattr(args, "serial", None),
            getattr(args, "timeout", 60),
        )
    available = [
        item
        for item in package["components"]
        if not item.get("variants") or context.target.variant in item["variants"]
    ]
    selected = [item for item in available if not args.component or item["name"] == args.component]
    if not selected:
        raise DevelopmentError("Package 没有匹配的 component；自定义交付需要声明 actions.build")
    unsupported = [item for item in selected if item["type"] != "vendor"]
    if unsupported:
        raise DevelopmentError("非 vendor Package 独立开发需要 actions.build 声明交付产物")
    roots = [directory / item["dir"] for item in selected]
    if args.action in {"run", "debug", "log", "test"} and len(roots) != 1:
        raise DevelopmentError("多个 vendor component：请使用 --component 选择运行对象")
    if args.action == "plan":
        return {"plans": [plan.to_dict() for plan in _builder(context, config).plan(roots)]}
    report = build_report(
        context,
        roots,
        config=config,
        force=getattr(args, "force", False),
        output_level=_output_level(args),
        no_build=getattr(args, "no_build", False) or args.action == "log",
    )
    if args.action == "build":
        return {**report_data(report), "build_log": str(context.target_dir / "build.log")}
    if explicit := package.get("actions", {}).get(args.action):
        return _action(
            explicit,
            forwarded,
            directory,
            context,
            report,
            args.action,
            getattr(args, "serial", None),
            getattr(args, "timeout", 60),
        )
    return operate_report(
        context,
        report,
        args.action,
        serial=getattr(args, "serial", None),
        args=forwarded,
        lines=getattr(args, "lines", None),
        since=getattr(args, "since", None),
        follow=not getattr(args, "no_follow", False),
        timeout=getattr(args, "timeout", 60),
        debug_mode=getattr(args, "mode", "target"),
        port=getattr(args, "port", 2345),
    )


def _parser() -> argparse.ArgumentParser:
    parser = ArgumentParser(prog="flange", description="工作区资源开发")
    resources = parser.add_subparsers(dest="resource", required=True)
    for resource in ("app", "package"):
        actions = resources.add_parser(resource).add_subparsers(dest="action", required=True)
        create = actions.add_parser("create", help="在当前目录创建工程")
        create.add_argument("name", help="工程名称，同时作为生成目录名")
        create.add_argument("--dir", type=Path, help="工程父目录，默认当前调用目录")
        create.add_argument(
            "--type",
            default="exec",
            choices=("exec", "service", "lib", "test", "amp"),
            help="App 类型，默认 exec",
        )
        create.add_argument(
            "--build-system",
            default="cmake",
            choices=("none", "cmake", "meson", "make", "swift", "amp", "scons"),
            help="原生构建系统，默认 cmake",
        )
        create.add_argument(
            "--arch",
            choices=SUPPORTED_APP_ARCHITECTURES,
            help="用户态架构，默认当前 target，未选择目标时为 aarch64",
        )
        create.add_argument("--version", default="0.1.0", help="初始版本号，默认 0.1.0")
        create.add_argument("--description", default="", help="项目描述")
        create.add_argument(
            "--embedded-swift", action="store_true", help="为 AMP/SCons 生成 Embedded Swift 静态库"
        )
        actions.add_parser("list", help=f"列出工作区与工具仓库中的 {resource}")
        for action in ("plan", "build", "deploy", "run", "debug", "log", "test"):
            descriptions = {
                "plan": "只读查看完整依赖与产物计划",
                "build": "构建完整依赖闭包并发布产物",
                "deploy": "校验并部署完整运行时依赖",
                "run": "部署并运行应用或启动服务",
                "debug": "部署并启动 GDB 调试会话",
                "log": "读取已部署服务日志",
                "test": "部署并执行带超时的测试",
            }
            child = actions.add_parser(
                action, help=descriptions[action], description=descriptions[action]
            )
            child.add_argument(
                "target", nargs="?", default=".", help="资源名称或路径，默认当前目录（.）"
            )
            if resource == "package":
                child.add_argument("--component", help="选择 Package 内一个 vendor component")
            if action == "build":
                child.add_argument(
                    "--force", "-f", action="store_true", help="忽略缓存并重建请求闭包"
                )
                verbosity = child.add_mutually_exclusive_group()
                verbosity.add_argument(
                    "-v",
                    "--verbose",
                    action="store_true",
                    help="显示编译器原始输出，完整内容仍写入 build.log",
                )
                verbosity.add_argument(
                    "-q",
                    "--quiet",
                    action="store_true",
                    help="仅显示构建摘要和失败上下文，完整内容写入 build.log",
                )
            if action in {"deploy", "run", "debug", "log", "test"}:
                child.add_argument("--serial", help="ADB 设备序列号；多设备时必须指定")
            if action in {"deploy", "run", "debug", "test"}:
                child.add_argument(
                    "--no-build", action="store_true", help="使用经清单校验的已有产物"
                )
            if action == "test":
                child.add_argument("--timeout", type=int, default=60, help="测试超时秒数，默认 60")
            if action == "debug":
                child.add_argument(
                    "--mode",
                    choices=("target", "remote"),
                    default="target",
                    help="GDB 在目标机或宿主机运行，默认 target",
                )
                child.add_argument(
                    "--port", type=int, default=2345, help="remote 模式 gdbserver 端口，默认 2345"
                )
            if action == "log":
                child.add_argument("--lines", type=int, help="最多读取的日志行数")
                child.add_argument("--since", help="journalctl 起始时间")
                child.add_argument("--no-follow", action="store_true", help="输出现有日志后退出")
    return parser


def execute(argv: Sequence[str] | None = None, *, context: WorkspaceContext | None = None) -> dict:
    """返回结构化结果；根 CLI 负责统一人类输出与 JSON envelope。"""
    values = list(sys.argv[1:] if argv is None else argv)
    if values[:1] in (["_build-app"], ["_build-package"]):
        if len(values) != 2:
            raise DevelopmentError("内部构建入口需要一个请求文件")
        return (_internal_build if values[0] == "_build-app" else _internal_package_build)(
            Path(values[1])
        )
    if "--" in values:
        index = values.index("--")
        options, forwarded = values[:index], values[index + 1 :]
    else:
        options, forwarded = values, []
    args = _parser().parse_args(options)
    if args.action == "create":
        if forwarded:
            raise DevelopmentError("create 不接受额外 argv")
        invocation = context.invocation_dir if context else Path.cwd()
        parent = (invocation / (args.dir or invocation).expanduser()).resolve()
        tool = context.tool_root if context else PROJECT_ROOT
        arch = args.arch or (userspace_arch(resolve_config(context)) if context else "aarch64")
        if args.resource == "app":
            path = AppScaffold(tool).create(
                args.name,
                args.type,
                args.build_system,
                parent_dir=parent,
                version=args.version,
                description=args.description,
                embedded_swift=args.embedded_swift,
                show_registration_hint=False,
                arch=arch,
            )
        else:
            if args.embedded_swift:
                raise DevelopmentError("Package create 尚不支持 embedded-swift")
            path = PackageScaffold(tool).create(
                args.name,
                parent_dir=parent,
                app_type=args.type,
                build_system=args.build_system,
                version=args.version,
                description=args.description,
                arch=arch,
            )
        return {"path": str(path), "resource": args.resource, "name": args.name}
    context = context or load_workspace()
    config = resolve_config(context)
    if args.action == "list":
        if args.resource == "package":
            from builder.packages import load_package_manifest_dir

            entries = {}
            search = [
                (context.tool_root / "components/packages", "tool"),
                (context.workspace_root, "workspace"),
                (context.workspace_root / "packages", "workspace"),
            ]
            for parent, origin in search:
                if not parent.is_dir():
                    continue
                for directory in sorted(parent.iterdir()):
                    if (directory / "package.py").is_file():
                        package = load_package_manifest_dir(directory)
                        entries[package["name"]] = {
                            "name": package["name"],
                            "path": str(directory),
                            "source": origin,
                            "components": [item["name"] for item in package["components"]],
                        }
            return {"packages": [entries[name] for name in sorted(entries)]}
        from builder.app_list import list_all

        entries = {
            entry.name: {"name": entry.name, "path": str(entry.source_path), "source": "tool"}
            for entry in list_all(context.tool_root, config)
        }
        discovered = {}
        for directory in context.app_dirs:
            if directory.is_dir():
                for child in sorted(directory.iterdir()):
                    if (child / "app.yaml").is_file():
                        if (
                            child.name in discovered
                            and discovered[child.name] != child.resolve()
                            and child.name not in context.apps
                        ):
                            raise DevelopmentError(
                                f"App {child.name!r} 有多个工作区来源，请在 [apps] 显式注册"
                            )
                        discovered[child.name] = child.resolve()
                        entries[child.name] = {
                            "name": child.name,
                            "path": str(child),
                            "source": "workspace-directory",
                        }
        entries.update(
            {
                name: {"name": name, "path": str(path), "source": "workspace"}
                for name, path in context.apps.items()
            }
        )
        return {"apps": [entries[name] for name in sorted(entries)]}
    return (_app_request if args.resource == "app" else _package_request)(
        args, forwarded, context, config
    )


def main(argv: Sequence[str] | None = None, *, context: WorkspaceContext | None = None) -> int:
    def report(error, *, code=1, kind="operation"):
        message = str(error) or ("操作已取消" if code == 130 else type(error).__name__)
        if not getattr(error, "_flange_reported", False):
            Presenter().error("build", message, code=code, kind=kind)
        write_failure(message, code=code, kind=kind)
        return code

    try:
        result = execute(argv, context=context)
        values = list(sys.argv[1:] if argv is None else argv)
        if values[:1] not in (["_build-app"], ["_build-package"]):
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return int(result.get("exit_code", 0))
    except BuildFailure as exc:
        return report(exc, code=exc.code, kind=exc.kind)
    except (
        ValueError,
        FileNotFoundError,
        RuntimeError,
        BuildError,
        subprocess.CalledProcessError,
    ) as exc:
        return report(exc)
    except KeyboardInterrupt as exc:
        return report(exc, code=130, kind="cancelled")
    except Exception as exc:
        error = RuntimeError(f"{type(exc).__name__}: {exc}")
        error._flange_reported = getattr(exc, "_flange_reported", False)
        return report(error, kind="internal")


if __name__ == "__main__":
    raise SystemExit(main())
