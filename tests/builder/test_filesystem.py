"""存储限制必须显式失败，不能关闭内核功能。"""

from pathlib import Path

import pytest

from builder.docker import BuildError
from builder.filesystem import require_case_sensitive
from builder.kernel_base import KernelBuilder
from builder.platforms.rockchip.kernel import RockchipKernelBuilder
from builder.source import SourceManager
from builder.workspace import Target, WorkspaceContext


def test_大小写不敏感存储报告迁移路径(tmp_path, monkeypatch):
    exists = Path.exists
    monkeypatch.setattr(Path, 'exists', lambda self: True if self.name == 'upper' else exists(self))
    with pytest.raises(BuildError, match='flange.toml.*build_dir'):
        require_case_sensitive(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_内核片段不再关闭netfilter(tmp_path, monkeypatch):
    monkeypatch.setattr('builder.filesystem.require_case_sensitive', lambda _: None)
    builder = RockchipKernelBuilder(None, None)
    builder._write_case_insensitive_fix(tmp_path)
    text = (tmp_path / 'arch' / builder.ARCH / 'configs/case_insensitive_fix.config').read_text()
    assert 'CONFIG_' not in text


def test_源码同步前先校验构建存储(tmp_path, monkeypatch):
    ctx = WorkspaceContext(tmp_path, tmp_path, tmp_path / '.build', Target('board', 'default', 'release'))
    def reject(_):
        raise BuildError('invalid filesystem')
    monkeypatch.setattr('builder.filesystem.require_case_sensitive', reject)
    manager = SourceManager(context=ctx)
    monkeypatch.setattr(manager, 'ensure', lambda *args: pytest.fail('门禁失败不能下载'))
    with pytest.raises(BuildError, match='invalid filesystem'):
        manager.prepare_cache_inputs('kernel', {'kernel': {'source': {'name': 'kernel'}}})
