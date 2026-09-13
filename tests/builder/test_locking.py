"""原子写的文件权限契约。"""

import stat

from builder.locking import atomic_write


def test_原子写的文件宿主机可读(tmp_path):
    """容器内 root 写的元数据要让宿主机普通用户读得到。"""
    path = tmp_path / 'manifest.json'
    atomic_write(path, '{}\n')
    assert path.read_text() == '{}\n'
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode & 0o044 == 0o044, f'文件权限 {mode:04o} 宿主机无法读取'


def test_锁目录与锁文件对另一侧用户可写(tmp_path):
    """宿主机用户与容器内 root 共用同一把目标锁：先创建的一方不能把另一方锁在外面。"""
    import os

    from builder.locking import FileLock, LOCK_DIR_MODE, LOCK_FILE_MODE

    previous = os.umask(0o077)
    try:
        lock = tmp_path / 'locks' / 'board-product-debug.lock'
        with FileLock(lock):
            pass
    finally:
        os.umask(previous)
    assert stat.S_IMODE(lock.parent.stat().st_mode) == LOCK_DIR_MODE
    assert stat.S_IMODE(lock.stat().st_mode) == LOCK_FILE_MODE


def test_锁文件不可写时给出修复提示(tmp_path):
    """旧版 flange 在容器内以 root 建的 0644 锁：报错要说清是谁的、怎么修。"""
    import os

    import pytest

    from builder.locking import FileLock

    lock = tmp_path / 'locks' / 'x.lock'
    lock.parent.mkdir()
    lock.touch(mode=0o444)
    if os.access(lock, os.W_OK):
        pytest.skip('root 运行时无法模拟权限拒绝')
    with pytest.raises(PermissionError, match='chown'):
        with FileLock(lock):
            pass
