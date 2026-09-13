"""构建资源的跨进程锁与原子文件写入。"""

from __future__ import annotations

import errno
import fcntl
import os
import stat
import tempfile
import threading
from pathlib import Path
from typing import IO

_HELD: dict[tuple[str, int, int], tuple[IO[str], int]] = {}
_GUARD = threading.RLock()

# 锁目录与锁文件同时被两侧使用：宿主机普通用户（app/package build、deploy、
# clean 先在宿主机申请目标锁）和构建容器内的 root（系统构建、run_logged）。谁先
# 创建，另一侧都必须还能 open+flock，所以目录 1777、文件 0666，与创建者无关。
LOCK_DIR_MODE = 0o1777
LOCK_FILE_MODE = 0o666


def _relax_mode(path: Path, mode: int) -> None:
    """把权限放宽到 mode；文件归另一个用户时 chmod 会失败，静默跳过。"""
    try:
        if stat.S_IMODE(path.stat().st_mode) != mode:
            path.chmod(mode)
    except OSError:
        pass


class FileLock:
    """同线程可重入的排他文件锁，异常或进程退出后由操作系统释放。"""

    def __init__(self, path: Path):
        self.path = Path(path).absolute()

    @property
    def _key(self):
        return (str(self.path), os.getpid(), threading.get_ident())

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _relax_mode(self.path.parent, LOCK_DIR_MODE)
        with _GUARD:
            held = _HELD.get(self._key)
            if held:
                stream, depth = held
                _HELD[self._key] = (stream, depth + 1)
                return self
        try:
            descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT, LOCK_FILE_MODE)
        except PermissionError as exc:
            raise PermissionError(
                errno.EACCES,
                f"无法打开锁文件 {self.path}：它归另一个用户所有（通常是旧版 flange 在"
                "构建容器内以 root 创建）。一次性修复后重试："
                f"sudo chown -R $(id -u):$(id -g) {self.path.parent}",
            ) from exc
        _relax_mode(self.path, LOCK_FILE_MODE)
        stream = os.fdopen(descriptor, "a+")
        try:
            fcntl.flock(stream, fcntl.LOCK_EX)
        except BaseException:
            stream.close()
            raise
        with _GUARD:
            _HELD[self._key] = (stream, 1)
        return self

    def __exit__(self, exc_type, exc, traceback):
        with _GUARD:
            stream, depth = _HELD[self._key]
            if depth > 1:
                _HELD[self._key] = (stream, depth - 1)
                return False
            del _HELD[self._key]
        fcntl.flock(stream, fcntl.LOCK_UN)
        stream.close()
        return False


def atomic_write(path: Path, content: str | bytes) -> None:
    """同目录唯一临时文件，完整写入并 fsync 后原子替换。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content.encode() if isinstance(content, str) else content)
            stream.flush()
            os.fsync(stream.fileno())
        # mkstemp 默认权限为 0600，而构建在 Docker 容器内以 root 运行；不放宽权限，
        # 宿主机非 root 用户便读不到写出的元数据（同 flash/model.py 的原子写）。
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
