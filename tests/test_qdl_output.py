"""使用模拟子进程验证实时进度和失败日志，不连接设备。"""

import io
import subprocess
import sys

import pytest

from builder.flash import qdl_output


@pytest.mark.parametrize("interactive", [False, True])
def test_output_and_log_arrive_before_child_finishes(tmp_path, monkeypatch, interactive):
    log = tmp_path / "qdl.log"
    release = tmp_path / "continue"

    class Console(io.StringIO):
        def isatty(self):
            return interactive

        def write(self, text):
            result = super().write(text)
            if "rootfs 50%" in self.getvalue():
                # 子进程在等这个信号，证明不是进程退出后才显示或保存输出。
                assert b"rootfs 50%" in log.read_bytes()
                release.touch()
            return result

    console = Console()
    monkeypatch.setattr(qdl_output.sys, "stdout", console)
    script = """
import os, pathlib, sys, time
assert os.isatty(1)
assert (os.get_terminal_size(1).columns > 0) == (sys.argv[2] == 'True')
os.write(1, b'rootfs 50%\\r')
signal = pathlib.Path(sys.argv[1])
while not signal.exists():
    time.sleep(0.01)
os.write(2, '写入完成\\n'.encode())
"""
    result = qdl_output.stream_qdl(
        [sys.executable, "-c", script, str(release), str(interactive)], tmp_path, log, 5)
    assert result == 0
    assert "写入完成" in console.getvalue()
    assert "写入完成" in log.read_text()


def test_failure_preserves_exit_code_and_diagnostic(tmp_path, capsys):
    log = tmp_path / "qdl.log"
    result = qdl_output.stream_qdl(
        [sys.executable, "-c", "import sys; print('NAK', flush=True); sys.exit(7)"],
        tmp_path, log, 5)
    assert result == 7
    assert "NAK" in capsys.readouterr().out
    assert b"NAK" in log.read_bytes()


def test_timeout_preserves_partial_log_and_reaps_child(tmp_path, monkeypatch):
    processes = []
    original = qdl_output.subprocess.Popen

    def start(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(qdl_output.subprocess, "Popen", start)
    log = tmp_path / "qdl.log"
    with pytest.raises(subprocess.TimeoutExpired):
        qdl_output.stream_qdl(
            [sys.executable, "-c", "import time; print('waiting', flush=True); time.sleep(30)"],
            tmp_path, log, 1)
    assert b"waiting" in log.read_bytes()
    assert len(processes) == 1
    assert processes[0].poll() is not None
