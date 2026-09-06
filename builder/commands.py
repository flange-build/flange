"""公共命令的应用层处理器；只负责服务编排，不解析 argv。"""

import os
import shlex
import shutil
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

from builder.paths import PROJECT_ROOT
from builder.presentation import (
    Presenter,
    UsageError,
    field,
    heading,
    render_checks,
    render_plan,
    render_why,
)
from builder.term import Role, style
from builder.workspace import (
    Target,
    WorkspaceError,
    discover_workspace,
    init_workspace,
    load_workspace,
    resolve_config,
    save_target,
    selected_target,
    workspace_settings,
)


def _container_environment(context) -> None:
    """只读查询实际镜像；缺少 Docker 时计划仍可展示未解析输入。"""
    from builder.docker import BuildError, DockerRunner, _is_inside_container

    if _is_inside_container():
        return
    try:
        runner = DockerRunner(context=context)
        context.environment_ids[runner.environment_name] = runner.environment_identity()
    except (BuildError, OSError, subprocess.SubprocessError, IndexError):
        pass


def _settings(start: Path) -> dict:
    return workspace_settings(discover_workspace(start))


def _doctor(start: Path, target=None) -> list[dict]:
    checks = [
        {
            "name": "Python",
            "ok": sys.version_info >= (3, 12),
            "detail": sys.version.split()[0],
            "fix": "安装 Python 3.12 或更新版本",
        }
    ]
    values = None
    try:
        values = _settings(start)
        checks.append(
            {
                "name": "工作区",
                "ok": True,
                "detail": str(values["workspace_root"]),
                "fix": "",
            }
        )
        root = values["tool_root"]
    except WorkspaceError as exc:
        root = PROJECT_ROOT
        checks.append(
            {"name": "工作区", "ok": False, "detail": str(exc), "fix": "flange init ."}
        )
    docker = shutil.which("docker")
    try:
        result = (
            subprocess.run(
                [docker, "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if docker
            else None
        )
        ready = result is not None and result.returncode == 0
        checks.append(
            {
                "name": "Docker",
                "ok": ready,
                "detail": result.stdout.strip() if ready else "守护进程不可用",
                "fix": "启动 Docker Desktop 或 Docker Engine",
            }
        )
        if ready:
            from builder.docker import DockerRunner

            try:
                context = None
                if values and (target or selected_target(values["workspace_root"], values["target"])):
                    context = load_workspace(start, target=target)
                runner = DockerRunner(root, context=context)
                identity = runner.environment_identity()
                checks.append(
                    {"name": "构建镜像", "ok": True, "detail": identity, "fix": ""}
                )
            except Exception as exc:
                checks.append(
                    {
                        "name": "构建镜像",
                        "ok": False,
                        "detail": str(exc),
                        "fix": "flange docker build",
                    }
                )
    except (OSError, subprocess.TimeoutExpired) as exc:
        checks.append(
            {
                "name": "Docker",
                "ok": False,
                "detail": str(exc),
                "fix": "启动 Docker 后重试",
            }
        )
    return checks


def _target(args, options, start: Path, output: Presenter) -> int:
    from builder.config.query import get_valid_targets

    settings = _settings(start)
    root, tool = settings["workspace_root"], settings["tool_root"]
    if args.action == "list":
        targets = [
            name for name in get_valid_targets(project_root=tool, layer_stack=settings["layer_stack"]) if args.filter in name
        ]
        output.result(
            "target list", targets, lines=[style(name, Role.ACTIVE) for name in targets]
        )
        return 0
    if args.action == "select":
        name = args.name
        if not name:
            if (
                options.no_interaction
                or options.json
                or not sys.stdin.isatty()
                or not sys.stdout.isatty()
            ):
                raise UsageError(
                    "此模式需要明确的目标名称。运行 flange target list，再运行 flange target select <target>"
                )
            from builder.lunch_tui import select_target

            current = selected_target(root, settings["target"])
            name = select_target(current.key if current else None, project_root=tool,
                                 layer_stack=settings["layer_stack"])
            if name is None:
                return 130
        target = Target.parse(name, tool, settings["layer_stack"])
        # 持久化之前完整求值，错误配置不能变成当前选择。
        context = load_workspace(start, target=target)
        resolve_config(context)
        save_target(root, target)
        output.result(
            "target select",
            context.to_dict(),
            lines=[
                f"{style('已选择', Role.SUCCESS)} {target.key}",
                field("工作区", root, Role.PATH),
                field(
                    "下一步",
                    "flange build 或 flange plan",
                    Role.COMMAND,
                ),
            ],
        )
        return 0
    context = load_workspace(start, target=options.target)
    config = resolve_config(context)
    from builder.config.summary import summarize_config

    sections = summarize_config(config)
    lines = [heading(context.target.key), ""]
    for title, rows in sections:
        lines.append(heading(title))
        lines.extend("  " + field(key, value) for key, value in rows)
    output.result(
        "target show", {"context": context.to_dict(), "config": config}, lines=lines
    )
    return 0


def _system(args, options, start: Path, output: Presenter) -> int:
    context = load_workspace(start, target=options.target)
    config = resolve_config(context)
    from builder.docker import DockerRunner, _is_inside_container

    if args.command != "build":
        _container_environment(context)
    if args.command == "build" and not _is_inside_container():
        runner = DockerRunner(context=context)
        from builder.oot_mounts import workspace_mounts

        command = [
            "python3",
            "-m",
            "builder",
            "--workspace",
            str(context.workspace_root),
            "--target",
            context.target.key,
            "build",
            args.component,
        ]
        for name in ("force", "force_all", "quiet", "verbose"):
            if getattr(args, name, False):
                command.append("--" + name.replace("_", "-"))
        from builder.build_result import run_build_container

        retry = ["flange"]
        if options.workspace:
            retry.extend(["-C", str(context.workspace_root)])
        if options.target:
            retry.extend(["--target", context.target.key])
        retry.append("build")
        if args.component != "image":
            retry.append(args.component)

        # JSON 由最外层入口生成；回执使用独立文件，不把协议混进终端日志。
        with redirect_stdout(sys.stderr):
            run_build_container(
                runner, command,
                cwd=str(context.workspace_root),
                privileged=True,
                extra_mounts=workspace_mounts(context, config),
                env={"FLANGE_BUILD_RETRY_COMMAND": shlex.join(retry)},
            )
        output.result(
            "build",
            {"target": context.target.key, "target_dir": str(context.target_dir)},
            lines=[],
        )
        return 0
    from builder.engine import BuildEngine
    from builder.output import OutputLevel

    level = OutputLevel.NORMAL
    if args.command == "build":
        level = (
            OutputLevel.VERBOSE
            if args.verbose
            else OutputLevel.QUIET
            if args.quiet
            else level
        )
    engine = BuildEngine(config, context=context, output_level=level)
    from builder.layer_diagnostics import composition_report, composition_lines
    composition = composition_report(config, context)
    if args.command == "plan":
        plans = [plan.to_dict() for plan in engine.plan(args.component)]
        output.result(
            "plan",
            {"target": context.target.key, "tasks": plans, "composition": composition},
            lines=render_plan(plans, context.target.key) + composition_lines(composition),
        )
    elif args.command == "why":
        reports = engine.explain(args.component)
        for report in reports:
            report["composition"] = composition
        output.result("why", reports, lines=render_why(reports, context.target.key) + composition_lines(composition))
    else:
        force = "all" if args.force_all else args.component if args.force else None
        with redirect_stdout(sys.stderr):
            engine.build(args.component, force=force)
        output.result(
            "build",
            {"target": context.target.key, "target_dir": str(context.target_dir)},
            lines=[],
        )
    return 0


def _layer(args, start: Path, output: Presenter) -> int:
    from builder.config.registry import discover_boards

    settings = _settings(start)
    stack = settings["layer_stack"]
    if args.action == "check":
        stack.check_providers()
        boards = discover_boards(settings["tool_root"], layer_stack=stack)
        data = {"layers": stack.to_dict(), "boards": sorted(boards)}
        lines = [f"层校验通过：{len(stack.layers)} 层，{len(boards)} 个板卡"]
    elif args.action == "show":
        if "/" in args.name:
            refs = stack.all(args.name)
            data = {"resource": args.name, "sources": [ref.to_dict() for ref in refs]}
            lines = [ref.identity for ref in refs] or ["资源不存在"]
        else:
            data = stack.layer(args.name).to_dict()
            lines = [f"{data['name']}: {data['root']}", f"依赖：{', '.join(data['requires']) or '无'}"]
    else:
        data = stack.to_dict()
        lines = [f"{item['order']}: {item['name']}  {item['root']}" for item in data]
    output.result(f"layer {args.action}", data, lines=lines)
    return 0


def _dispatch(args, options, start: Path, output: Presenter) -> int:
    if args.command == "layer":
        return _layer(args, start, output)
    if args.command == "init":
        path = (
            args.directory if args.directory.is_absolute() else start / args.directory
        )
        manifest = init_workspace(path, tool_root=args.tool_root, target=options.target)
        output.result(
            "init",
            {"manifest": str(manifest)},
            lines=[
                f"{style('已创建工作区', Role.SUCCESS)}  {style(manifest.parent, Role.PATH)}",
                field("配置", manifest, Role.PATH),
                field(
                    "下一步", f"flange -C {manifest.parent} target list", Role.COMMAND
                ),
            ],
        )
        return 0
    if args.command == "target":
        return _target(args, options, start, output)
    if args.command == "doctor" or (
        args.command == "docker" and args.action == "status"
    ):
        checks = _doctor(start, options.target)
        ready = all(check["ok"] for check in checks)
        output.result(
            args.command,
            {"ready": ready, "checks": checks},
            ok=ready,
            lines=render_checks(checks),
        )
        return 0 if ready else 1
    if args.command in {"build", "plan", "why"}:
        return _system(args, options, start, output)
    if args.command == "status":
        values = _settings(start)
        chosen = (
            Target.parse(options.target, values["tool_root"])
            if options.target
            else selected_target(values["workspace_root"], values["target"])
        )
        data = {
            "workspace_root": str(values["workspace_root"]),
            "tool_root": str(values["tool_root"]),
            "build_root": str(values["build_root"]),
            "target": chosen.to_dict() if chosen else None,
        }
        lines = [
            field("工作区", values["workspace_root"], Role.PATH),
            field("工具  ", values["tool_root"], Role.PATH),
            field(
                "目标  ",
                chosen.key if chosen else "尚未选择",
                Role.ACTIVE if chosen else Role.WARNING,
            ),
            field("产物根", values["build_root"], Role.PATH),
        ]
        if chosen:
            context = load_workspace(start, target=chosen)
            data["target_dir"] = str(context.target_dir)
            data["manifests"] = (
                [
                    str(path)
                    for path in sorted(context.target_dir.rglob("manifest.json"))
                ]
                if context.target_dir.exists()
                else []
            )
            lines.append(field("当前产物", context.target_dir, Role.PATH))
            lines.append(
                field(
                    "下一步",
                    "flange why 查看缓存决策；flange plan 查看构建计划",
                    Role.COMMAND,
                )
            )
        else:
            lines.append(field("下一步", "flange target select <target>", Role.COMMAND))
        output.result("status", data, lines=lines)
        return 0
    if args.command == "docker":
        from builder.docker import DockerRunner

        settings = _settings(start)
        context = None
        if options.target or selected_target(settings["workspace_root"], settings["target"]):
            context = load_workspace(start, target=options.target)
        runner = DockerRunner(settings["tool_root"], context=context)
        command = runner.compose_command(
            "build", *(["--no-cache"] if args.action == "rebuild" else [])
        )
        subprocess.run(command, stdout=sys.stderr, check=True)
        output.result(
            "docker " + args.action,
            {"image": runner.environment_identity()},
            lines=[style("构建环境已准备好", Role.SUCCESS)],
        )
        return 0
    if args.command == "recovery":
        from builder.recovery_host import main

        with redirect_stdout(sys.stderr):
            code = main(args.arguments)
        if code:
            raise RuntimeError("recovery 操作失败；诊断信息见 stderr")
        output.result("recovery", {"exit_code": code}, lines=[])
        return code
    if args.command == "flash" and any(
        flag in args.arguments for flag in ("-h", "--help")
    ):
        from builder.flash.execute import _cli_main

        _cli_main(args.arguments, public=True)
        return 0
    context = load_workspace(start, target=options.target)
    if args.command == "clean":
        from builder.locking import FileLock

        paths = [context.target_dir, context.build_root / "work" / context.target.key]
        if not args.dry_run:
            with FileLock(context.build_root / "locks" / f"{context.target.key}.lock"):
                for path in paths:
                    if path.is_symlink():
                        path.unlink()
                    elif path.exists():
                        shutil.rmtree(path)
        output.result(
            "clean",
            {"dry_run": args.dry_run, "paths": paths},
            lines=[
                style("将清理：", Role.WARNING)
                if args.dry_run
                else style("已清理：", Role.SUCCESS),
                *("  " + style(path, Role.PATH) for path in paths),
            ],
        )
        return 0
    if args.command == "shell":
        if not args.arguments and (
            options.no_interaction or options.json or not sys.stdin.isatty()
        ):
            raise UsageError(
                "无交互模式需要明确命令，例如 flange shell -- python3 --version"
            )
        from builder.docker import DockerRunner
        from builder.oot_mounts import workspace_mounts

        command = args.arguments or ["bash"]
        if command[0] == "--":
            command = command[1:]
        with redirect_stdout(sys.stderr):
            DockerRunner(context=context).run(
                command,
                cwd=str(context.workspace_root),
                extra_mounts=workspace_mounts(context, resolve_config(context)),
            )
        output.result("shell", {"exit_code": 0}, lines=[])
        return 0
    if args.command == "flash":
        if not (context.target_dir / "flash-config.json").is_file():
            raise RuntimeError(
                f"缺少 {context.target_dir / 'flash-config.json'}；请先运行 flange build image"
            )
        from builder.flash.execute import _cli_main

        with redirect_stdout(sys.stderr):
            _cli_main(
                args.arguments,
                public=True,
                target_dir=context.target_dir,
                project_dir=context.tool_root,
                layer_stack=context.layer_stack,
            )
        output.result("flash", {"target": context.target.key}, lines=[])
        return 0
    raise UsageError(f"未知命令：{args.command}")
