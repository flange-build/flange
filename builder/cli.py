"""flange 公共命令入口：解析意图，建立上下文，调用服务，呈现结果。"""

import argparse
import os
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

from builder.build_result import BuildFailure, write_failure
from builder.commands import _container_environment, _dispatch
from builder.graph import DEPENDENCY_GRAPH
from builder.paths import PROJECT_ROOT
from builder.presentation import ArgumentParser, Presenter, UsageError, render_resource
from builder.workspace import (
    WorkspaceError,
    discover_workspace,
    load_workspace,
    selected_target,
    workspace_settings,
)


def _creation_context(start: Path, target: str | None):
    """创建工程可以没有目标；已有工作区的显式配置错误仍必须被报告。"""
    try:
        root = discover_workspace(start)
    except WorkspaceError:
        if target:
            raise
        return None
    settings = workspace_settings(root)
    chosen = target or selected_target(root, settings["target"])
    return load_workspace(start, target=chosen) if chosen else None


def _creation_arguments(arguments: list[str], start: Path) -> list[str]:
    """-C 的目录语义同样适用于无需选择目标的脚手架。"""
    values = list(arguments)
    for index, value in enumerate(values):
        if value.startswith("--dir="):
            path = Path(value.split("=", 1)[1]).expanduser()
            values[index] = "--dir=" + str((start / path).resolve())
            return values
        if value == "--dir":
            if index + 1 < len(values) and not values[index + 1].startswith("-"):
                path = Path(values[index + 1]).expanduser()
                values[index + 1] = str((start / path).resolve())
            return values
    return values + ["--dir", str(start)]


def _global_parser() -> ArgumentParser:
    parser = ArgumentParser(add_help=False, allow_abbrev=False, prog="flange")
    parser._optionals.title = "全局选项"
    parser.add_argument(
        "-C", "--workspace", type=Path, help="在指定工作区执行（不改变调用者目录）"
    )
    parser.add_argument("--target", help="仅本次使用该目标，不修改工作区选择")
    parser.add_argument("--json", action="store_true", help="输出带版本号的 JSON 结果")
    parser.add_argument("--no-color", action="store_true", help="关闭 ANSI 颜色与动画")
    parser.add_argument(
        "--no-interaction", action="store_true", help="禁止交互提示，适用于 CI"
    )
    return parser


def _parser() -> ArgumentParser:
    parser = ArgumentParser(
        prog="flange",
        parents=[_global_parser()],
        allow_abbrev=False,
        description="从工作区到设备的嵌入式 Linux 开发工具。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""开始使用：
  flange init ~/workspace/my-product --tool-root /path/to/flange
  cd ~/workspace/my-product
  flange docker build
  flange target list
  flange target select radxa-zero3w-default-release
  flange app create hello --build-system cmake
  flange app build ./hello
  flange plan image
  flange build image

帮助：flange <命令> --help   ·   诊断：flange doctor
退出码：0 成功，1 操作失败，2 参数/配置错误，130 用户取消。
全局选项可放在命令前后；-- 之后的参数原样传给应用。""",
    )
    parser.add_argument(
        "--version", action="version", version="flange 3.0.0", help="显示版本并退出"
    )
    commands = parser.add_subparsers(dest="command", title="命令")
    init = commands.add_parser("init", help="创建独立工作区")
    init.add_argument("directory", nargs="?", type=Path, default=Path("."))
    init.add_argument("--tool-root", type=Path, default=PROJECT_ROOT)
    target = commands.add_parser("target", help="浏览、选择或检查目标")
    actions = target.add_subparsers(dest="action", required=True)
    listing = actions.add_parser("list", help="列出可用目标")
    listing.add_argument("filter", nargs="?", default="", help="按名称过滤")
    selection = actions.add_parser("select", help="选择工作区目标；TTY 中可交互选择")
    selection.add_argument("name", nargs="?")
    actions.add_parser("show", help="显示当前目标的有效配置摘要")
    layer = commands.add_parser("layer", help="查看和校验本地扩展层")
    layer_actions = layer.add_subparsers(dest="action", required=True)
    layer_actions.add_parser("list", help="按优先级列出启用层")
    layer_actions.add_parser("check", help="校验层清单、依赖及配置目标")
    layer_show = layer_actions.add_parser("show", help="查看层声明或资源覆盖链")
    layer_show.add_argument("name", help="层名称或 components 下的资源路径")
    commands.add_parser("status", help="显示工作区、目标及已记录的产物")
    commands.add_parser("doctor", help="检查 Python、Docker 和工作区，并给出修复步骤")
    for name, help_text in (
        ("plan", "预览依赖和产物，不执行构建"),
        ("why", "解释缓存命中或重建原因"),
        ("build", "在 Docker 中构建系统组件及其依赖"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument(
            "component", nargs="?", default="image", choices=tuple(DEPENDENCY_GRAPH)
        )
        if name == "build":
            command.add_argument(
                "-f", "--force", action="store_true", help="强制重建指定组件"
            )
            command.add_argument(
                "--force-all", action="store_true", help="强制重建整个依赖闭包"
            )
            verbosity = command.add_mutually_exclusive_group()
            verbosity.add_argument(
                "-v", "--verbose", action="store_true", help="显示编译器原始输出"
            )
            verbosity.add_argument(
                "-q", "--quiet", action="store_true", help="仅显示摘要与失败上下文"
            )
    for resource, help_text in (
        ("app", "创建、构建、部署、运行、测试和调试 App"),
        ("package", "管理 App 包与 vendor SDK 开发流程"),
        ("flash", "在宿主机刷写镜像或查看分区"),
        ("recovery", "设备恢复模式、备份与维护"),
    ):
        command = commands.add_parser(resource, help=help_text, add_help=False)
        command.add_argument("arguments", nargs=argparse.REMAINDER)
    docker = commands.add_parser("docker", help="准备或检查容器构建环境")
    docker.add_argument("action", choices=("build", "rebuild", "status"))
    shell = commands.add_parser("shell", help="进入当前工作区的容器环境")
    shell.add_argument("arguments", nargs=argparse.REMAINDER)
    clean = commands.add_parser("clean", help="清理当前目标的产物与中间目录")
    clean.add_argument("--dry-run", action="store_true", help="只列出待清理目录")
    return parser


def _finish_error(output, command, error, *, code, kind):
    """构建已给出完整诊断时不重复打印；机器调用仍获得结构化错误。"""
    message = str(error) or ("操作已取消" if code == 130 else type(error).__name__)
    if output.machine or not getattr(error, "_flange_reported", False):
        output.error(command, message, code=code, kind=kind)
    write_failure(message, code=code, kind=kind)
    return code


def main(argv: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    output = Presenter(
        machine="--json" in values[: values.index("--")]
        if "--" in values
        else "--json" in values
    )
    command = "flange"
    previous_environment = {
        key: os.environ.get(key)
        for key in ("NO_COLOR", "FLANGE_NO_INTERACTION", "FLANGE_BUILD_ENVIRONMENT")
    }
    try:
        # -- 后的 argv 属于用户程序，不能被全局解析器消费。
        boundary = values.index("--") if "--" in values else len(values)
        # 参数解析本身也可能失败；错误呈现仍须遵守用户请求的无颜色模式。
        if output.machine or "--no-color" in values[:boundary]:
            os.environ["NO_COLOR"] = "1"
        options, remaining = _global_parser().parse_known_args(values[:boundary])
        remaining += values[boundary:]
        output = Presenter(machine=options.json)
        if options.no_color or options.json:
            os.environ["NO_COLOR"] = "1"
        if options.no_interaction or options.json:
            os.environ["FLANGE_NO_INTERACTION"] = "1"
        start = Path(options.workspace or Path.cwd()).resolve()
        command = remaining[0] if remaining else "flange"
        if len(remaining) == 1 and command in {
            "app",
            "package",
            "target",
            "docker",
            "recovery",
        }:
            remaining.append("--help")
        if command in {"app", "package"}:
            from builder import dev

            resource_options = (
                remaining[: remaining.index("--")] if "--" in remaining else remaining
            )
            if any(flag in resource_options for flag in ("-h", "--help")):
                dev.execute(remaining)
                return 0
            context = None
            if remaining[1] == "create":
                remaining = _creation_arguments(remaining, start)
                context = _creation_context(start, options.target)
            else:
                context = load_workspace(start, target=options.target)
                _container_environment(context)
            with redirect_stdout(sys.stderr):
                result = dev.execute(remaining, context=context)
            code = result.get("exit_code", 0)
            output.result(
                " ".join(remaining[:2]),
                result,
                ok=code == 0,
                lines=render_resource(remaining[1], result),
            )
            return code
        if command in {"flash", "recovery"}:
            return _dispatch(
                argparse.Namespace(command=command, arguments=remaining[1:]),
                options,
                start,
                output,
            )
        parser = _parser()
        if not remaining:
            parser.print_help()
            return 0
        args = parser.parse_args(remaining)
        return _dispatch(args, options, start, output)
    except SystemExit as exc:
        return int(exc.code or 0)
    except KeyboardInterrupt as exc:
        if not getattr(exc, "_flange_reported", False):
            exc = RuntimeError("操作已停止。已有日志保留，可修复后重新运行同一命令")
        return _finish_error(output, command, exc, code=130, kind="cancelled")
    except BrokenPipeError:
        return 0
    except BuildFailure as exc:
        return _finish_error(output, command, exc, code=exc.code, kind=exc.kind)
    except (UsageError, WorkspaceError, ValueError, KeyError) as exc:
        return _finish_error(output, command, exc, code=2, kind="configuration")
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        return _finish_error(output, command, exc, code=1, kind="operation")
    except Exception as exc:
        # 意外异常仍然保留类型，避免把编程错误误报为可重试的环境错误。
        error = RuntimeError(f"{type(exc).__name__}: {exc}")
        error._flange_reported = getattr(exc, "_flange_reported", False)
        return _finish_error(output, command, error, code=1, kind="internal")
    finally:
        for key, value in previous_environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
