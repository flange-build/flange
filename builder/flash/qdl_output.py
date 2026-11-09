"""通过伪终端转发 QDL 进度，同时持续保存刷写日志。"""

import codecs
import errno
import fcntl
import os
import pty
import select
import shutil
import struct
import subprocess
import sys
import termios
import time
from pathlib import Path


def stream_qdl(command: list[str], directory: Path, log: Path, timeout: float) -> int:
    """QDL 仅向有宽度的终端输出进度；重定向时保留普通分区消息。"""
    master, slave = pty.openpty()
    process = None
    try:
        width = min(120, max(40, shutil.get_terminal_size().columns)) if sys.stdout.isatty() else 0
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, width, 0, 0))
        deadline = time.monotonic() + timeout
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        with log.open("wb") as output:
            process = subprocess.Popen(command, cwd=directory, stdin=subprocess.DEVNULL,
                                       stdout=slave, stderr=slave)
            os.close(slave)
            slave = -1
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, timeout)
                if not select.select([master], [], [], min(remaining, 0.2))[0]:
                    continue
                try:
                    chunk = os.read(master, 65536)
                except OSError as exc:
                    if exc.errno != errno.EIO:
                        raise
                    chunk = b""  # Linux PTY 关闭时返回 EIO，macOS 返回 EOF。
                if not chunk:
                    break
                output.write(chunk)
                output.flush()
                sys.stdout.write(decoder.decode(chunk))
                sys.stdout.flush()
            sys.stdout.write(decoder.decode(b"", final=True))
            sys.stdout.flush()
            return process.wait(timeout=max(0, deadline - time.monotonic()))
    finally:
        # 超时、中断或输出异常时回收本次子进程，不自动重试刷写。
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)
        if slave >= 0:
            os.close(slave)
