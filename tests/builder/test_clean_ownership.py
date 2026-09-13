"""flange clean：宿主机删不动 root 留下的目录时改在容器内删除。"""

import os
from unittest.mock import MagicMock, patch

import pytest

from builder.commands import _remove_build_tree


def test_宿主机能删就直接删(tmp_path):
    tree = tmp_path / 'target'
    (tree / 'apps').mkdir(parents=True)
    with patch('builder.docker.DockerRunner') as runner:
        _remove_build_tree(tree, context=MagicMock())
    assert not tree.exists()
    runner.assert_not_called()


def test_权限拒绝时进容器删除(tmp_path, monkeypatch):
    tree = tmp_path / 'work'
    locked = tree / 'rootfs' / 'run-x'
    locked.mkdir(parents=True)
    (locked / 'f').touch()
    locked.chmod(0o500)
    if os.access(locked, os.W_OK):
        pytest.skip('root 运行时无法模拟权限拒绝')
    monkeypatch.setattr('builder.docker._is_inside_container', lambda: False)
    try:
        with patch('builder.docker.DockerRunner') as runner:
            _remove_build_tree(tree, context=MagicMock())
        runner.return_value.run.assert_called_once_with(
            ['rm', '-rf', str(tree)], capture=True
        )
    finally:
        locked.chmod(0o700)
