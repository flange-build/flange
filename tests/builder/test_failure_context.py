"""失败诊断属于命令异常，不能被后续清理或已处理失败污染。"""

import subprocess
import sys

import pytest

from builder.docker import BuildError, DockerRunner
from builder.output import BuildOutput
from builder.process import run_logged


DETAIL = " unable to open '/etc/sudoers.d/README.dpkg-new': Permission denied"
FAIL = [sys.executable, "-c", (
    "import sys; print('dpkg: error processing archive sudo.deb (--unpack):'); "
    f"print({DETAIL!r}); "
    "[print('Unpacking other package') for _ in range(30)]; "
    "print('E: Sub-process /usr/bin/dpkg returned an error code (1)'); sys.exit(100)"
)]
CLEANUP = [sys.executable, "-c", "print('cleanup-only: unmounted successfully')"]


@pytest.mark.parametrize("executor", ["docker", "process"])
@pytest.mark.parametrize("capture", [False, True])
def test_失败后成功清理仍显示原始APT权限诊断(tmp_path, capsys, monkeypatch, executor, capture):
    output = BuildOutput(tmp_path)
    output.build_start("rootfs", {"board": "test"})
    output.phase_start("rootfs")
    runner = DockerRunner(output=output)
    runner._in_container = True

    def run(command):
        if executor == "docker":
            return runner.run(command, capture=capture)
        return run_logged(command, output, check=True,
                          **({"capture_output": True, "text": True} if capture else {}))

    with pytest.raises((BuildError, subprocess.CalledProcessError)) as failed:
        run(FAIL)
    diagnostic = failed.value._flange_command_diagnostic
    assert DETAIL in diagnostic.lines
    assert diagnostic.command == tuple(FAIL)
    run(CLEANUP)
    assert DETAIL not in output._errors and DETAIL not in output._tail_buffer
    assert failed.value._flange_command_diagnostic is diagnostic
    output.phase_end("rootfs", success=False, error=failed.value)
    output.build_end(success=False)
    terminal = capsys.readouterr().out
    assert "Permission denied" in terminal
    assert "/etc/sudoers.d/README.dpkg-new" in terminal
    assert "cleanup-only" not in terminal
    assert "\033" not in terminal
    log = (tmp_path / "build.log").read_text()
    assert DETAIL in log and "cleanup-only" in log


def test_两次命令失败分别保存上下文(tmp_path):
    output = BuildOutput(tmp_path)
    try:
        with pytest.raises(subprocess.CalledProcessError) as first:
            run_logged(FAIL, output, check=True)
        cleanup = [sys.executable, "-c", "import sys; print('fatal: cleanup failure'); sys.exit(1)"]
        with pytest.raises(subprocess.CalledProcessError) as second:
            run_logged(cleanup, output, check=True)
        assert DETAIL in first.value._flange_command_diagnostic.lines
        assert "fatal: cleanup failure" not in first.value._flange_command_diagnostic.lines
        assert second.value._flange_command_diagnostic.lines == ("fatal: cleanup failure",)
    finally:
        output.close()


def test_宿主Docker失败快照不被后续清理覆盖(tmp_path, capsys, monkeypatch):
    output = BuildOutput(tmp_path)
    output.build_start("rootfs", {"board": "test"})
    runner = DockerRunner(output=output)
    runner._in_container = False
    monkeypatch.setattr(runner, "environment_identity", lambda: "sha256:test")
    monkeypatch.setattr(runner, "compose_command", lambda *args: FAIL)
    with pytest.raises(BuildError) as failed:
        runner.run(["apt-get", "install", "sudo"])
    assert failed.value._flange_command_diagnostic.command == ("apt-get", "install", "sudo")
    monkeypatch.setattr(runner, "compose_command", lambda *args: CLEANUP)
    runner.run(["umount", "/rootfs/dev"])
    output.build_end(success=False, error=failed.value)
    terminal = capsys.readouterr().out
    assert DETAIL in terminal and "cleanup-only" not in terminal


def test_容器启动前失败不能借用上一条命令诊断(tmp_path, capsys, monkeypatch):
    output = BuildOutput(tmp_path)
    output.build_start("rootfs", {"board": "test"})
    output.command_start(["previous"])
    output.feed_line("fatal: previous unrelated error")
    runner = DockerRunner(output=output)
    runner._in_container = False

    def unavailable():
        raise BuildError("Docker 不可用")

    monkeypatch.setattr(runner, "environment_identity", unavailable)
    with pytest.raises(BuildError) as failed:
        runner.run(["apt-get", "install", "sudo"])
    output.build_end(success=False, error=failed.value)
    terminal = capsys.readouterr().out
    assert "Docker 不可用" in terminal and "previous unrelated error" not in terminal


def test_清理失败作为补充保留主错误诊断(tmp_path, capsys):
    output = BuildOutput(tmp_path)
    output.build_start("rootfs", {"board": "test"})
    with pytest.raises(subprocess.CalledProcessError) as failed:
        run_logged(FAIL, output, check=True)
    run_logged(CLEANUP, output, check=True)
    failed.value.add_note("清理失败：umount /rootfs/dev 返回 32")
    output.build_end(success=False, error=failed.value)
    terminal = capsys.readouterr().out
    assert "Permission denied" in terminal
    assert "补充  清理失败：umount /rootfs/dev 返回 32" in terminal


def test_已处理失败不污染后来配置错误(tmp_path, capsys):
    output = BuildOutput(tmp_path)
    output.build_start("rootfs", {"board": "test"})
    with pytest.raises(subprocess.CalledProcessError):
        run_logged(FAIL, output, check=True)
    run_logged(CLEANUP, output, check=True)
    output.build_end(success=False, error=ValueError("配置中的分区名称重复"))
    terminal = capsys.readouterr().out
    assert "配置中的分区名称重复" in terminal
    assert "Permission denied" not in terminal and "cleanup-only" not in terminal


@pytest.mark.parametrize("capture", [False, True])
def test_超时异常在清理后保留本命令上下文(tmp_path, capsys, capture):
    output = BuildOutput(tmp_path)
    output.build_start("rootfs", {"board": "test"})
    command = [sys.executable, "-c", f"import time; print({DETAIL!r}, flush=True); time.sleep(30)"]
    with pytest.raises(subprocess.TimeoutExpired) as failed:
        run_logged(command, output, timeout=0.2,
                   **({"capture_output": True, "text": True} if capture else {}))
    run_logged(CLEANUP, output, check=True)
    output.build_end(success=False, error=failed.value)
    assert DETAIL in failed.value._flange_command_diagnostic.lines
    assert "Permission denied" in capsys.readouterr().out


def test_无错误模式的失败仍冻结尾部(tmp_path, capsys):
    output = BuildOutput(tmp_path)
    output.build_start("rootfs", {"board": "test"})
    command = [sys.executable, "-c", "import sys; print('tool stopped during unpack'); sys.exit(1)"]
    with pytest.raises(subprocess.CalledProcessError) as failed:
        run_logged(command, output, check=True)
    run_logged(CLEANUP, output, check=True)
    output.build_end(success=False, error=failed.value)
    terminal = capsys.readouterr().out
    assert "tool stopped during unpack" in terminal and "cleanup-only" not in terminal
