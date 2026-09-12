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
