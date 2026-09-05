"""命令结果的终端与 JSON 呈现；业务服务不依赖终端状态。"""

import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path

from builder.term import Role, style, terminal_width, wrap


class UsageError(ValueError):
    """无效命令参数，退出码为 2。"""


class ArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)
        self._positionals.title = "参数"
        self._optionals.title = "选项"
        for action in self._actions:
            if isinstance(action, argparse._HelpAction):
                action.help = "显示帮助并退出"

    def error(self, message):
        raise UsageError(f"{message}\n运行 {self.prog} --help 查看用法")


def json_value(value):
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (set, tuple)):
        return list(value)
    raise TypeError(f"无法序列化 {type(value).__name__}")


class Presenter:
    """stdout 只承载结果；诊断与过程信息使用 stderr。"""

    def __init__(self, *, machine: bool = False):
        self.machine = machine

    def result(
        self, command: str, data, *, lines: list[str] | None = None, ok: bool = True
    ):
        if self.machine:
            self._json(
                {"schema_version": 1, "command": command, "ok": ok, "data": data}
            )
        elif lines is not None:
            for line in lines:
                print(line)
        else:
            print(json.dumps(data, ensure_ascii=False, indent=2, default=json_value))

    def error(self, command: str, message: str, *, code: int, kind: str):
        if self.machine:
            self._json(
                {
                    "schema_version": 1,
                    "command": command,
                    "ok": False,
                    "error": {"kind": kind, "message": message, "exit_code": code},
                }
            )
            return
        prefix = "错误" if code != 130 else "已取消"
        prefix = style(
            prefix, Role.WARNING if code == 130 else Role.ERROR, stream=sys.stderr
        )
        print(f"{prefix}：{message}", file=sys.stderr)

    @staticmethod
    def _json(value):
        print(json.dumps(value, ensure_ascii=False, default=json_value))


def heading(text: str) -> str:
    return style(text, Role.HEADING)


def field(label: str, value: object, role: Role = Role.TEXT) -> str:
    """标签退后，值保留完整内容；路径与下一步命令有明确语义。"""
    return f"{style(label, Role.MUTED)}  {style(value, role)}"


def render_ready() -> str:
    """Shell 薄入口也复用角色定义，避免在脚本内维护另一组颜色码。"""
    return (
        style("flange 已就绪", Role.SUCCESS)
        + " · "
        + style("flange --help", Role.COMMAND)
        + " 查看命令"
        + " · "
        + style("lunch", Role.COMMAND)
        + " 选择当前工作区目标"
    )


def render_checks(checks: list[dict]) -> list[str]:
    lines = []
    for check in checks:
        state = (
            style("通过", Role.SUCCESS)
            if check["ok"]
            else style("待处理", Role.WARNING)
        )
        lines.append(f"{state}  {check['name']} · {check['detail']}")
        if not check["ok"]:
            lines.append("        " + style(check["fix"], Role.COMMAND))
    return lines


def render_why(reports: list[dict], target: str) -> list[str]:
    """依据缓存决策着色；正常的未命中是构建信息，不是警告或错误。"""
    states = {
        "hit": ("可复用", Role.SUCCESS),
        "miss": ("需重建", Role.ACTIVE),
        "disabled": ("已禁用", Role.MUTED),
        "blocked": ("待准备", Role.WARNING),
    }
    lines = [heading(f"缓存决策 · {target}"), ""]
    for report in reports:
        label, role = states.get(report.get("status"), ("需重建", Role.ACTIVE))
        lines.append(f"  {report['task_id']} · {style(label, role)}")
        if report.get("note"):
            lines.append(f"    {report['note']}")
        for reason in report.get("reasons", []):
            value = (
                reason.get("segment", reason) if isinstance(reason, dict) else reason
            )
            lines.append(f"    {value}")
    return lines


def render_plan(plans: list[dict], target: str) -> list[str]:
    """以依赖先行的顺序显示计划；不把组件数量伪装成剩余时间。"""
    lines = [heading(f"构建计划 · {target}"), ""]
    for index, plan in enumerate(plans, 1):
        enabled = plan.get("enabled", True)
        task_id = plan.get("task_id", plan.get("id", "?"))
        dependencies = plan.get("dependencies", [])
        lines.append(
            f"  {index:>2}. "
            + style(task_id, Role.ACTIVE if enabled else Role.MUTED)
            + (style(" · 已禁用", Role.MUTED) if not enabled else "")
        )
        if dependencies:
            lines.append("      " + field("依赖", ", ".join(dependencies)))
        for output in plan.get("outputs", []):
            location = output.get("path", output.get("name", ""))
            lines.extend(
                "      " + field("产物", line, Role.PATH)
                for line in wrap(str(location), max(1, terminal_width() - 12))
            )
    lines += [
        "",
        style("计划未执行构建；未下载的源码会在执行时解析并记录。", Role.MUTED),
    ]
    return lines


def render_resource(action: str, result: dict) -> list[str]:
    """人类摘要只呈现操作结果与下一步；完整结构保留在 JSON 接口。"""
    if action == "create":
        return [
            f"{style('已创建', Role.SUCCESS)} {result['resource']} · {result['name']}",
            field("目录", result["path"], Role.PATH),
            field(
                "下一步",
                f"flange {result['resource']} build {result['path']}",
                Role.COMMAND,
            ),
        ]
    if "plans" in result:
        return render_plan(result["plans"], "App")
    if "packages" in result:
        lines = [heading("Package"), ""]
        for package in result["packages"]:
            lines.append(f"  {package['name']}")
            lines.append("    " + style(package["path"], Role.PATH))
        return lines
    if "apps" in result:
        lines = [
            heading("应用")
            if action == "list"
            else style("App 构建完成", Role.SUCCESS),
            "",
        ]
        for app in result["apps"]:
            state = " · " + style("已复用", Role.SUCCESS) if app.get("reused") else ""
            lines.append(f"  {app['name']}{state}")
            for package in app.get("packages", []):
                role = "运行包" if package["role"] == "runtime" else "开发包"
                lines.append(f"    {role} · {package['format'].upper()}")
                lines.append("      " + style(package["path"], Role.PATH))
            if action == "list":
                lines.append(f"    {style(app['path'], Role.PATH)} · {app['source']}")
        if result.get("identity"):
            lines += ["", field("产物身份", result["identity"][:16])]
        if result.get("build_log"):
            lines.append(field("构建日志", result["build_log"], Role.PATH))
        return lines
    status = result.get("status", "failed" if result.get("exit_code") else "succeeded")
    states = {
        "succeeded": ("完成", Role.SUCCESS),
        "passed": ("通过", Role.SUCCESS),
        "failed": ("失败", Role.ERROR),
        "timed_out": ("超时", Role.ERROR),
        "interrupted": ("已取消", Role.WARNING),
    }
    label, role = states.get(status, (status, Role.TEXT))
    lines = [f"{action} · {style(label, role)}"]
    if result.get("device"):
        device = result["device"]
        lines.append(field("设备", device.get("serial") or device.get("transport", "")))
    if result.get("exit_code"):
        lines.append(field("退出码", result["exit_code"]))
    if result.get("error"):
        lines.append(field("原因", result["error"]))
    for key, label in (
        ("build_log", "构建日志"),
        ("report_path", "会话记录"),
        ("stdout_path", "标准输出"),
        ("stderr_path", "错误输出"),
    ):
        if result.get(key):
            lines.append(field(label, result[key], Role.PATH))
    if action == "run" and result.get("stdout"):
        lines += ["", result["stdout"].rstrip()]
    if result.get("test"):
        for key in ("stdout_path", "stderr_path"):
            if result["test"].get(key):
                lines.append(field("日志", result["test"][key], Role.PATH))
    return lines
