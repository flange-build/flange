"""构建资源的跨进程锁与原子文件写入。"""

from __future__ import annotations

import fcntl
import os
import tempfile
import threading
from pathlib import Path
from typing import IO

_HELD: dict[tuple[str, int, int], tuple[IO[str], int]] = {}
_GUARD = threading.RLock()


class FileLock:
    """同线程可重入的排他文件锁，异常或进程退出后由操作系统释放。"""

    def __init__(self, path: Path):
        self.path = Path(path).absolute()

    @property
    def _key(self):
        return (str(self.path), os.getpid(), threading.get_ident())

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _GUARD:
            held = _HELD.get(self._key)
            if held:
                stream, depth = held
                _HELD[self._key] = (stream, depth + 1)
                return self
        stream = self.path.open("a+")
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
