"""真实小型 Git 仓库验证目标工作树、用户源码和变更检测。"""

import subprocess
import threading
from pathlib import Path

import pytest

from builder.graph import InputSpec
from builder.locking import FileLock
from builder.source import SourceManager
from builder.workspace import Target, WorkspaceContext


def context(tmp_path, variant):
    return WorkspaceContext(tmp_path, tmp_path, tmp_path / '.build', Target('board', 'default', variant))


def git(path, *args):
    return subprocess.run(['git', *args], cwd=path, capture_output=True, text=True, check=True).stdout.strip()


def repository(path):
    path.mkdir()
    git(path, 'init')
    git(path, 'config', 'user.email', 'test@example.invalid')
    git(path, 'config', 'user.name', '测试')
    (path / 'source.c').write_text('original')
    git(path, 'add', '.')
    git(path, 'commit', '-m', '初始版本')
    return git(path, 'rev-parse', 'HEAD')


def test_两个目标共享下载但不共享可变工作树(tmp_path):
    upstream = tmp_path / 'upstream'
    revision = repository(upstream)
    config = {'sources': {'kernel': {'url': str(upstream), 'commit': revision}},
              'kernel': {'source': {'name': 'kernel'}}}
    first, second = SourceManager(context=context(tmp_path, 'release')), SourceManager(context=context(tmp_path, 'debug'))
    one = first.ensure('kernel', config)
    two = second.ensure('kernel', config)
    assert one != two
    assert one.parent != upstream.parent
    (one / 'source.c').write_text('target-patch')
    assert (two / 'source.c').read_text() == 'original'
    assert (upstream / 'source.c').read_text() == 'original'
    assert len(list(first.sources_dir.joinpath('repos').iterdir())) == 1
    assert git(one, 'rev-parse', 'HEAD') == revision


def test_本地工作树按内容复制且不覆盖用户改动(tmp_path):
    original = tmp_path / 'local'
    repository(original)
    (original / 'source.c').write_text('user edits')
    config = {'sources': {'local': {'local_path': str(original)}}, 'kernel': {'source': {'name': 'local'}}}
    manager = SourceManager(context=context(tmp_path, 'release'))
    assert not manager.source_path('kernel', config).exists()
    target = manager.ensure('kernel', config)
    assert target != original
    assert not (target / '.git').exists()
    (target / 'source.c').write_text('compiler mutation')
    (target / 'object.o').write_text('object')
    assert manager.ensure('kernel', config) == target
    assert (target / 'object.o').exists()
    assert (original / 'source.c').read_text() == 'user edits'
    (original / 'source.c').write_text('next user edit')
    manager.ensure('kernel', config)
    assert (target / 'source.c').read_text() == 'next user edit'
    assert not (target / 'object.o').exists()
    assert 'source.c' in git(original, 'status', '--porcelain')


def test_git输入在执行前后重新读取HEAD(tmp_path):
    repo = tmp_path / 'repo'
    revision = repository(repo)
    source = InputSpec.git('source', repo, revision)
    before = source.digest()
    (repo / 'source.c').write_text('new')
    git(repo, 'add', '.')
    git(repo, 'commit', '-m', '更新')
    assert source.digest() != before


def test_排他锁跨线程串行且异常释放(tmp_path):
    lock_path = tmp_path / 'resource.lock'
    attempting, acquired = threading.Event(), threading.Event()
    shared_lock = FileLock(lock_path)

    def worker():
        attempting.set()
        with shared_lock:
            acquired.set()

    with pytest.raises(RuntimeError):
        with shared_lock:
            with shared_lock:
                thread = threading.Thread(target=worker)
                thread.start()
                assert attempting.wait(1)
                assert not acquired.wait(0.05)
            raise RuntimeError('cancel')
    thread.join(timeout=2)
    assert acquired.is_set()
