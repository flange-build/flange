"""使用真实子进程验证源码日志、诊断、超时与取消。"""

import subprocess
import sys

import pytest

from builder.output import BuildOutput, OutputLevel
from builder.source import SourceManager


@pytest.mark.parametrize("level", [OutputLevel.NORMAL, OutputLevel.VERBOSE])
def test_源码命令双流进入日志且遵守输出级别(tmp_path, capsys, level):
    output = BuildOutput(tmp_path / "target", level=level)
    manager = SourceManager(tmp_path / "sources", output=output)
    try:
        manager._run([
            sys.executable, "-c",
            "import sys; print('Git 标准输出'); print('Git 进度输出', file=sys.stderr)",
        ], check=True)
    finally:
        output.close()
    terminal = capsys.readouterr()
    log = (tmp_path / "target/build.log").read_text()
    for line in ("Git 标准输出", "Git 进度输出"):
        assert line in log
        assert (line in terminal.out) is (level == OutputLevel.VERBOSE)
    assert terminal.err == ""
    assert "\033" not in terminal.out + log


def test_源码查询保留返回值与失败诊断(tmp_path, capsys):
    output = BuildOutput(tmp_path)
    manager = SourceManager(tmp_path / "sources", output=output)
    try:
        with pytest.raises(subprocess.CalledProcessError) as failed:
            manager._run([
                sys.executable, "-c",
                "import sys; print('revision'); print('fatal: 源码不可用', file=sys.stderr); sys.exit(3)",
            ], check=True, capture_output=True, text=True)
        assert failed.value.stdout == "revision\n"
        assert "fatal: 源码不可用" in failed.value.stderr
    finally:
        output.close()
    assert "fatal: 源码不可用" in (tmp_path / "build.log").read_text()
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("capture", [False, True])
def test_源码命令超时保留之前的输出(tmp_path, capture):
    output = BuildOutput(tmp_path)
    manager = SourceManager(tmp_path / "sources", output=output)
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            manager._run([
                sys.executable, "-c",
                "import time; print('准备源码', flush=True); time.sleep(30)",
            ], timeout=0.2, **({"capture_output": True, "text": True} if capture else {}))
    finally:
        output.close()
    assert "准备源码" in (tmp_path / "build.log").read_text()


def test_取消会停止源码工具及其子进程(tmp_path):
    """同进程组中的工作进程必须收到取消信号。"""
    pid_file = tmp_path / "child.pid"
    marker = tmp_path / "stopped"
    child = (
        "import signal, time; from pathlib import Path; "
        f"signal.signal(signal.SIGTERM, lambda *_: (Path({str(marker)!r}).touch(), exit(0))); "
        f"Path({str(pid_file)!r}).write_text('ready'); time.sleep(30)"
    )
    parent = (
        "import subprocess, sys, time; from pathlib import Path; "
        f"subprocess.Popen([sys.executable, '-c', {child!r}]); "
        f"\nwhile not Path({str(pid_file)!r}).exists(): time.sleep(0.01)\n"
        "print('ready', flush=True); time.sleep(30)"
    )

    class CancelOutput:
        def command_start(self, cmd):
            pass

        def command_failed(self, error):
            pass

        def feed_line(self, line):
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        SourceManager(output=CancelOutput())._run([sys.executable, "-c", parent])
    assert marker.exists()
