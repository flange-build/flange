"""配置、源码、环境和内容输入的实际失效行为。"""

from copy import deepcopy
from pathlib import Path

import pytest

from builder.component_plan import create_component_plan
from builder.environment import environment_identity
from builder.source import SourceManager
from builder.workspace import Target, WorkspaceContext


def setup(tmp_path):
    ctx = WorkspaceContext(tmp_path, tmp_path, tmp_path / '.build', Target('board', 'default', 'release'))
    config = {'board': 'board', 'platform': 'rockchip', 'soc': 'rk3566',
              'architecture': {'kernel': 'arm64', 'userspace': 'aarch64', 'bootloader': 'arm64'},
              'kernel': {'device_tree': {'directory': '', 'name': 'board'}},
              'rootfs': {'packages': []}, 'bootloader': {}, 'recovery': {'enabled': True},
              'amp': {'enabled': True}, 'sources': {}}
    return ctx, config


def fingerprint(component, config, ctx):
    plan = create_component_plan(component, config, ctx, SourceManager(context=ctx))
    return plan.fingerprint({name: 'artifact-id' for name in plan.dependencies}).digest


@pytest.mark.parametrize('component,key', [('kernel', 'kernel'), ('kernel', 'boot'),
    ('bootloader', 'bootloader'), ('bootloader', 'amp'), ('rootfs', 'rootfs'),
    ('rootfs', 'partitions'), ('recovery', 'recovery'), ('amp', 'kernel'), ('amp', 'amp')])
def test_实际消费配置改变必须失效(tmp_path, component, key):
    ctx, config = setup(tmp_path)
    before = fingerprint(component, config, ctx)
    config.setdefault(key, {})['test_setting'] = 2
    assert fingerprint(component, config, ctx) != before


def test_执行配置与哈希边界相同(tmp_path):
    ctx, config = setup(tmp_path)
    before = fingerprint('kernel', config, ctx)
    config['rootfs']['packages'].append('curl')
    plan = create_component_plan('kernel', config, ctx, SourceManager(context=ctx))
    assert 'rootfs' not in plan.value('config')
    assert fingerprint('kernel', config, ctx) == before


def test_源码内容权限改变即失效但不哈希输出树(tmp_path):
    ctx, config = setup(tmp_path)
    source = tmp_path / 'local'
    source.mkdir()
    payload = source / 'main.c'
    payload.write_text('code')
    config['sources'] = {'local': {'local_path': str(source)}}
    config['kernel']['source'] = {'name': 'local'}
    before = fingerprint('kernel', config, ctx)
    payload.chmod(0o755)
    assert fingerprint('kernel', config, ctx) != before
    unchanged = fingerprint('kernel', config, ctx)
    ctx.build_root.mkdir()
    (ctx.build_root / 'result').write_text('irrelevant')
    assert fingerprint('kernel', config, ctx) == unchanged


def test_目录链接与panel固件变化被识别(tmp_path):
    ctx, config = setup(tmp_path)
    overlay = ctx.components_root / 'board/board/overlay'
    overlay.mkdir(parents=True)
    link = overlay / 'service'
    link.symlink_to('a', target_is_directory=True)
    before = fingerprint('rootfs', config, ctx)
    link.unlink()
    link.symlink_to('b', target_is_directory=True)
    assert fingerprint('rootfs', config, ctx) != before
    panel = ctx.components_root / 'board/board/panel.txt'
    panel.write_text('a')
    config['rootfs']['panel_firmware'] = [{'src': 'panel.txt'}]
    before = fingerprint('rootfs', config, ctx)
    panel.write_text('b')
    assert fingerprint('rootfs', config, ctx) != before


def test_sdk实现变化使AMP失效(tmp_path):
    ctx, config = setup(tmp_path)
    sdk = ctx.components_root / 'amp/rockchip/hal/lib'
    sdk.mkdir(parents=True)
    code = sdk / 'driver.c'
    code.write_text('a')
    before = fingerprint('amp', config, ctx)
    code.write_text('b')
    assert fingerprint('amp', config, ctx) != before


def test_环境镜像ID是宿主与容器共同身份(monkeypatch):
    monkeypatch.setenv('FLANGE_BUILD_ENVIRONMENT', 'sha256:immutable')
    assert environment_identity() == {'image': 'sha256:immutable'}
    assert environment_identity(emulator='qemu-arm-static') == environment_identity()
