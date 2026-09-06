"""构建日志的用户任务契约：即时反馈、诚实计时、单次失败与可复制恢复入口。"""

import shlex

import pytest

from builder.output import BuildOutput, OutputLevel, strip_ansi
from builder.term import display_width


@pytest.mark.parametrize("level", list(OutputLevel))
def test_开始反馈与完整日志不依赖颜色或输出级别(tmp_path, capsys, level):
    output = BuildOutput(tmp_path, level)
    with output.step("编译内核"):
        started = capsys.readouterr().out
        assert ("· 编译内核" in started) is (level != OutputLevel.QUIET)
        assert "✔" not in started
        output.feed_line("compiler output")
    output.close()
    result = capsys.readouterr().out
    assert ("✔ 编译内核" in result) is (level != OutputLevel.QUIET)
    assert ("compiler output" in result) is (level == OutputLevel.VERBOSE)
    log = (tmp_path / "build.log").read_text()
    assert "· 编译内核" in log and "✔ 编译内核" in log and "compiler output" in log


def test_完成通知不吸收下一段工作的耗时(tmp_path, capsys, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("builder.output.time.monotonic", lambda: clock[0])
    output = BuildOutput(tmp_path)
    output.status("配置文件已生成")
    clock[0] += 120
    with output.step("编译内核"):
        clock[0] += 30
    output.close()
    text = capsys.readouterr().out
    notification = next(line for line in text.splitlines() if "配置文件" in line)
    assert "✔" not in notification and "2m" not in notification
    assert "30.0s" in text


def test_嵌套命令不提前完成父动作且保留各自耗时(tmp_path, capsys, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("builder.output.time.monotonic", lambda: clock[0])
    output = BuildOutput(tmp_path)
    with output.step("构建 App hello"):
        clock[0] += 2
        output.spinner_start("编译源码")
        clock[0] += 3
        output.spinner_stop()
        during = capsys.readouterr().out
        assert "✔ 编译源码" in during and "3.0s" in during
        assert "✔ 构建 App hello" not in during
        assert output._step_label == "构建 App hello"
        clock[0] += 1
    finished = capsys.readouterr().out
    assert "✔ 构建 App hello" in finished and "6.0s" in finished
    output.close()


def test_失败只解释一次且不展示上一条命令的诊断(tmp_path, capsys):
    output = BuildOutput(tmp_path)
    output.plan(["kernel", "app", "rootfs", "image"])
    output.build_start("image", {"board": "test"})
    output.phase_skip("kernel")
    output.phase_start("app")
    output.command_start(["previous-tool"])
    output.feed_line("fatal: 已处理的旧问题")
    output.command_start(["current-tool"])
    output.feed_line("本次安装记录")
    failure = ValueError("App 运行入口未安装：/usr/bin/hello")
    output.phase_end("app", success=False, error=failure)
    output.build_end(success=False)
    output.build_end(success=False)
    text = capsys.readouterr().out
    assert text.count(str(failure)) == 1
    assert text.count("构建失败") == 1 and "未执行 2" in text
    assert "已处理的旧问题" not in text and "本次安装记录" not in text
    assert "flange build" in text and failure._flange_reported is True
    assert "fatal:" in (tmp_path / "build.log").read_text()


def test_恢复命令保留工作区目标和带空格资源路径(tmp_path, capsys):
    command = ["flange", "-C", str(tmp_path / "my workspace"), "--target",
               "board-default-debug", "app", "build", str(tmp_path / "my app")]
    output = BuildOutput(tmp_path, retry_command=shlex.join(command))
    output.build_start("app", {"board": "board"})
    output.build_end(success=False, error=RuntimeError("编译失败"))
    retry = capsys.readouterr().out.split("修复后重试  ")[1].splitlines()[0]
    assert shlex.split(retry) == command


@pytest.mark.parametrize("width", [40, 60, 80, 120])
def test_活动行显示真实顺序与耗时且不推算百分比(tmp_path, monkeypatch, width):
    monkeypatch.setattr("builder.output.terminal_width", lambda: width)
    output = BuildOutput(tmp_path)
    output.plan(["kernel", "rootfs"])
    output._current_component = "kernel"
    output._step_label = "编译内核及驱动模块"
    output._step_start = 1
    line = strip_ansi(output._sticky_line())
    assert "[1/2]" in line and "已用" in line and "%" not in line
    assert display_width(line) < width
    output._step_label = ""
    output.close()


def test_工具的颜色光标和超链接序列不泄漏到日志(tmp_path, capsys):
    output = BuildOutput(tmp_path, OutputLevel.VERBOSE)
    output.feed_line("\033[2K\r\033[32mCC main.o\033[0m \033]8;;https://example.com\a链接\033]8;;\a")
    output.close()
    for text in (capsys.readouterr().out, (tmp_path / "build.log").read_text()):
        assert "CC main.o" in text and "链接" in text
        assert "\033" not in text and "\r" not in text
