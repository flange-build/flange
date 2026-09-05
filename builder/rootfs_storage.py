"""rootfs 活树使用容器原生存储，归档和最终镜像才跨宿主共享边界。"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Iterator

from builder.docker import BuildError


def _active_mounts(directory: Path) -> list[Path]:
    """清理前读取当前挂载命名空间，避免递归删除仍挂载的 /dev 等目录。"""
    if sys.platform != "linux":
        return []
    root = directory.resolve()
    mounts = []
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        # mountinfo 用八进制转义表示空格、制表符、换行和反斜线。
        field = line.split()[4]
        mount = Path(re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), field))
        if mount == root or root in mount.parents:
            mounts.append(mount)
    return mounts


@contextmanager
def rootfs_staging(component: str) -> Iterator[Path]:
    """在单次构建容器中持有原生文件树，所有阶段结束后安全释放。

    明确使用容器 /var/tmp，不跟随可能指向宿主共享卷的 TMPDIR。
    调用方将镜像和清单写入持久工作目录；本目录只承载可变 Linux 文件树。
    """
    directory = Path(tempfile.mkdtemp(prefix=f"flange-{component}-", dir="/var/tmp"))
    error = None
    try:
        rootfs = directory / component
        rootfs.mkdir()
        yield rootfs
    except BaseException as exc:
        error = exc
        raise
    finally:
        try:
            mounts = _active_mounts(directory)
            if mounts:
                raise BuildError(
                    f"rootfs 临时目录仍有挂载，已保留目录并停止清理：{directory}；"
                    f"挂载点：{', '.join(map(str, mounts))}"
                )
            shutil.rmtree(directory)
        except Exception as cleanup_error:
            if error is None:
                raise
            error.add_note(f"rootfs 临时目录清理失败：{cleanup_error}")
