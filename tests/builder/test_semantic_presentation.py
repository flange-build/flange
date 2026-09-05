"""验证状态语义、真实输出流及机器接口边界，不依赖文字关键词猜测状态。"""

import io
import json
import os
import sys

import pytest

from builder.cli import main
from builder.output import strip_ansi
from builder.presentation import Presenter, render_ready, render_resource, render_why
from builder.term import Role, style
from builder.workspace import init_workspace


class Terminal(io.StringIO):
    def __init__(self, tty=True):
        super().__init__()
        self.tty = tty

    def isatty(self):
        return self.tty


@pytest.fixture
def terminal(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")

    def attach():
        stdout, stderr = Terminal(), Terminal()
        monkeypatch.setattr(sys, "stdout", stdout)
        monkeypatch.setattr(sys, "stderr", stderr)
        return stdout, stderr

    return attach


@pytest.mark.parametrize("control", ["pipe", "dumb", "empty_no_color", "no_color"])
def test_禁色保留全部文字而非只关闭色相(terminal, monkeypatch, control):
    terminal = terminal()
    stdout, _ = terminal
    colored = render_ready()
    assert "\033[" in colored
    if control == "pipe":
        stdout.tty = False
    elif control == "dumb":
        monkeypatch.setenv("TERM", "dumb")
    else:
        monkeypatch.setenv("NO_COLOR", "" if control == "empty_no_color" else "1")
    assert render_ready() == strip_ansi(colored)
    assert style("次要说明", Role.MUTED) == "次要说明"


@pytest.mark.parametrize("stdout_tty,stderr_tty", [(False, True), (True, False)])
def test_结果与诊断分别检查自己的输出流(terminal, stdout_tty, stderr_tty):
    terminal = terminal()
    stdout, stderr = terminal
    stdout.tty, stderr.tty = stdout_tty, stderr_tty
    output = Presenter()
    output.result("ready", {}, lines=[render_ready()])
    output.error("build", "缺少源码", code=1, kind="operation")
    assert ("\033[" in stdout.getvalue()) is stdout_tty
    assert ("\033[" in stderr.getvalue()) is stderr_tty
    assert strip_ansi(stderr.getvalue()) == "错误：缺少源码\n"


def test_替换输出流后不沿用导入时能力(terminal, monkeypatch):
    terminal = terminal()
    assert "\033[" in style("完成", Role.SUCCESS)
    monkeypatch.setattr(sys, "stdout", Terminal(tty=False))
    assert style("完成", Role.SUCCESS) == "完成"


@pytest.mark.parametrize(
    "status,label,role",
    [
        ("hit", "可复用", Role.SUCCESS),
        ("miss", "需重建", Role.ACTIVE),
        ("blocked", "待准备", Role.WARNING),
        ("disabled", "已禁用", Role.MUTED),
    ],
)
def test_缓存决策按事实区分复用待执行和阻塞(terminal, status, label, role):
    terminal = terminal()
    lines = render_why([{"task_id": "kernel", "status": status}], "board-default-debug")
    assert lines[2] == "  kernel · " + style(label, role)
    assert strip_ansi(lines[2]) == "  kernel · " + label


@pytest.mark.parametrize(
    "status,label,role",
    [
        ("passed", "通过", Role.SUCCESS),
        ("failed", "失败", Role.ERROR),
        ("timed_out", "超时", Role.ERROR),
        ("interrupted", "已取消", Role.WARNING),
    ],
)
def test_失败和取消不会显示为成功(terminal, status, label, role):
    terminal = terminal()
    assert render_resource("test", {"status": status})[0] == "test · " + style(
        label, role
    )


def test_取消诊断使用黄色并保留消息(terminal):
    terminal = terminal()
    _, stderr = terminal
    Presenter().error("build", "操作已停止", code=130, kind="cancelled")
    assert (
        stderr.getvalue()
        == style("已取消", Role.WARNING, stream=stderr) + "：操作已停止\n"
    )


def test_路径包含失败字样不会被当成错误(terminal):
    terminal = terminal()
    result = {"resource": "app", "name": "warning", "path": "/tmp/失败/warning"}
    lines = render_resource("create", result)
    assert style(result["path"], Role.PATH) in lines[1]
    assert style("flange app build /tmp/失败/warning", Role.COMMAND) in lines[2]
    assert style("已创建", Role.SUCCESS) in lines[0]
    assert "\033[1;31m" not in "\n".join(lines)


def test_JSON模式在真实终端能力下也保持过程纯文本(tmp_path, terminal, monkeypatch):
    terminal = terminal()
    from builder import dev

    init_workspace(tmp_path)

    def execute(*args, **kwargs):
        print(style("检查完成", Role.SUCCESS))
        return {"resource": "app", "name": "hello", "path": str(tmp_path / "hello")}

    monkeypatch.setattr(dev, "execute", execute)
    stdout, stderr = terminal
    assert main(["--json", "-C", str(tmp_path), "app", "create", "hello"]) == 0
    assert json.loads(stdout.getvalue())["data"]["name"] == "hello"
    assert stderr.getvalue() == "检查完成\n"
    assert "\033" not in stdout.getvalue()
    assert "NO_COLOR" not in os.environ


def test_命令禁色只作用本次调用且普通状态有颜色(tmp_path, terminal):
    terminal = terminal()
    init_workspace(tmp_path)
    stdout, _ = terminal
    assert main(["--no-color", "-C", str(tmp_path), "status"]) == 0
    plain = stdout.getvalue()
    assert "\033" not in plain
    stdout.seek(0)
    stdout.truncate()
    assert main(["-C", str(tmp_path), "status"]) == 0
    assert "\033" in stdout.getvalue()
    assert strip_ansi(stdout.getvalue()) == plain
    assert "NO_COLOR" not in os.environ


def test_全局参数解析失败也遵守禁色(terminal):
    stdout, stderr = terminal()
    assert main(["--no-color", "--workspace"]) == 2
    assert not stdout.getvalue()
    assert "错误" in stderr.getvalue()
    assert "\033" not in stderr.getvalue()
    assert "NO_COLOR" not in os.environ
