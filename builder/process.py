"""将构建子进程的完整输出交给同一个日志通道。"""

import os
import signal
import subprocess
import threading


def _signal_process(proc, number):
    """一起停止工具及其子进程，避免 Git/SSH 在取消后继续占用锁。"""
    try:
        os.killpg(proc.pid, number)
    except ProcessLookupError:
        pass


def run_logged(cmd, output, *, check=False, timeout=None, start_command=True, **kwargs):
    """在异常离开命令边界前冻结诊断，避免调用方清理命令覆盖。"""
    try:
        return _run_logged(
            cmd, output, check=check, timeout=timeout, start_command=start_command, **kwargs
        )
    except BaseException as error:
        if output is not None:
            output.command_failed(error)
        raise


def _run_logged(cmd, output, *, check=False, timeout=None, start_command=True, **kwargs):
    """流式记录工具输出；查询保留返回值，超时和取消传播给调用方。"""
    if output is None:
        if timeout is not None:
            kwargs["timeout"] = timeout
        return subprocess.run(cmd, check=check, **kwargs)
    if start_command:
        output.command_start(cmd)
    if kwargs.get("capture_output"):
        kwargs.pop("capture_output")
        proc = subprocess.Popen(
            [str(value) for value in cmd], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, start_new_session=True, **kwargs,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except BaseException:
            _signal_process(proc, signal.SIGKILL)
            stdout, stderr = proc.communicate()
            _feed(output, stdout, stderr)
            raise
        _feed(output, stdout, stderr)
        result = subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
        if check:
            result.check_returncode()
        return result

    proc = subprocess.Popen(
        [str(value) for value in cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
        **kwargs,
    )
    expired = threading.Event()

    def expire():
        expired.set()
        _signal_process(proc, signal.SIGKILL)

    timer = threading.Timer(timeout, expire) if timeout is not None else None
    if timer:
        timer.start()
    try:
        for line in proc.stdout:
            output.feed_line(line)
        proc.wait()
    except BaseException:
        _signal_process(proc, signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _signal_process(proc, signal.SIGKILL)
            proc.wait()
        raise
    finally:
        if timer:
            timer.cancel()
        proc.stdout.close()
    if expired.is_set():
        raise subprocess.TimeoutExpired(cmd, timeout)
    result = subprocess.CompletedProcess(cmd, proc.returncode)
    if check:
        result.check_returncode()
    return result


def _feed(output, *values):
    for value in values:
        if isinstance(value, bytes):
            value = value.decode(errors="replace")
        for line in (value or "").splitlines(keepends=True):
            output.feed_line(line)
