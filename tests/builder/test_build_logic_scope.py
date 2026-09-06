"""从实际配方展开实现输入，保证平台扩展和共享实现不会漏失效。"""

import shutil
from pathlib import Path

import pytest

from builder.component_plan import recipe_files
from builder.digest import digest_value, hash_path
from builder.workspace import Target, WorkspaceContext

ROOT = Path(__file__).resolve().parents[2]


def ctx(root):
    return WorkspaceContext(root, root, root / '.build', Target('board', 'default', 'release'))


def scope(root, component):
    return recipe_files(component, {'platform': 'rockchip'}, ctx(root))


def fingerprint(root, component):
    return digest_value({str(path.relative_to(root)): hash_path(path) for path in scope(root, component)})


@pytest.mark.parametrize('component', ['kernel', 'bootloader'])
def test_配方闭包包含基类实际平台和发布契约(component):
    names = {path.relative_to(ROOT).as_posix() for path in scope(ROOT, component)}
    required = {'builder/base.py', 'builder/source.py', 'builder/docker.py', 'builder/patches.py',
                'builder/engine.py', 'builder/artifacts.py', 'builder/component_plan.py',
                f'builder/platforms/rockchip/{component}.py', 'builder/platforms/rockchip/__init__.py'}
    assert required <= names


@pytest.mark.parametrize('relative,component', [
    ('kernel_base.py', 'kernel'), ('platforms/rockchip/kernel.py', 'kernel'),
    ('platforms/rockchip/bootloader.py', 'bootloader'), ('base.py', 'kernel'),
    ('platforms/rockchip/__init__.py', 'kernel'),
])
def test_修改实际依赖使配方失效(tmp_path, relative, component):
    shutil.copytree(ROOT / 'builder', tmp_path / 'builder', ignore=shutil.ignore_patterns('__pycache__'))
    before = fingerprint(tmp_path, component)
    path = tmp_path / 'builder' / relative
    path.write_text(path.read_text() + '\n# 配方变更\n')
    assert fingerprint(tmp_path, component) != before


def test_新增静态依赖自动进入闭包(tmp_path):
    shutil.copytree(ROOT / 'builder', tmp_path / 'builder', ignore=shutil.ignore_patterns('__pycache__'))
    helper = tmp_path / 'builder/new_helper.py'
    helper.write_text('VALUE = 1\n')
    kernel = tmp_path / 'builder/platforms/rockchip/kernel.py'
    kernel.write_text(kernel.read_text() + '\nimport builder.new_helper\n')
    assert helper in scope(tmp_path, 'kernel')
    before = fingerprint(tmp_path, 'kernel')
    helper.write_text('VALUE = 2\n')
    assert fingerprint(tmp_path, 'kernel') != before


def test_其他平台实现不进入当前叶子配方():
    assert not any('platforms/amlogic/' in str(path) for path in scope(ROOT, 'kernel'))
