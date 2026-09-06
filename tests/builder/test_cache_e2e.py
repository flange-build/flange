"""系统配置的第一阶段切口：执行和缓存使用同一份输入。"""

from copy import deepcopy
from pathlib import Path

import pytest

from builder.rootfs_base import apt_command, base_plan
from builder.workspace import Target, WorkspaceContext


def config():
    return {'architecture': {'userspace': 'aarch64', 'kernel': 'arm64', 'bootloader': 'arm64'},
            'rootfs': {'url': 'https://example.invalid/base.tar.gz', 'sha256': 'a' * 64,
                       'packages': ['systemd'], 'install_recommends': False},
            'recovery': {'packages': ['systemd'], 'install_recommends': False}}


def context(tmp_path, variant='release'):
    return WorkspaceContext(tmp_path, tmp_path, tmp_path / '.build', Target('board', 'default', variant))


def test_rootfs_recovery相同APT输入共享base身份(tmp_path):
    cfg = config()
    assert base_plan(cfg, 'rootfs', context(tmp_path)).fingerprint() == base_plan(cfg, 'recovery', context(tmp_path, 'debug')).fingerprint()


@pytest.mark.parametrize('field,value', [('packages', ['systemd', 'curl']),
    ('install_recommends', True), ('extra_apt_sources', [{'name': 'vendor', 'source': 'deb x', 'key': {'url': 'x', 'sha256': 'b' * 64}}])])
def test_recovery专有APT输入全部进入执行与快照身份(tmp_path, field, value):
    cfg = config()
    ctx = context(tmp_path)
    before = base_plan(cfg, 'recovery', ctx)
    cfg['recovery'][field] = value
    after = base_plan(cfg, 'recovery', ctx)
    assert after.fingerprint() != before.fingerprint()
    key = 'extra_sources' if field == 'extra_apt_sources' else field
    assert after.value('apt')[key] == (sorted(value) if field == 'packages' else value)
    assert base_plan(cfg, 'rootfs', ctx).fingerprint() == before.fingerprint()


def test_emulator_tarball环境与配方均属于base输入(tmp_path, monkeypatch):
    cfg, ctx = config(), context(tmp_path)
    before = base_plan(cfg, 'rootfs', ctx).fingerprint()
    cfg['rootfs']['emulator'] = 'qemu-custom-static'
    assert base_plan(cfg, 'rootfs', ctx).fingerprint() != before
    cfg = config()
    monkeypatch.setenv('FLANGE_ENVIRONMENT_PROVIDER', 'ubuntu')
    monkeypatch.setenv('FLANGE_BUILD_ENVIRONMENT', 'sha256:new')
    assert base_plan(cfg, 'rootfs', ctx).fingerprint() != before


def test_安装命令由APT输入直接生成():
    assert apt_command({'packages': ['systemd'], 'install_recommends': False}) == ['apt-get', 'install', '-y', '--no-install-recommends', 'systemd']
    assert '--no-install-recommends' not in apt_command({'packages': ['systemd'], 'install_recommends': True})
