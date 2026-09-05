"""容器边界验证：同绝对路径、去重挂载、构建环境身份和管道输出。"""

import os
from unittest.mock import MagicMock, patch

import pytest

from builder.docker import DockerRunner
from builder.workspace import Target, WorkspaceContext


@pytest.fixture
def host(monkeypatch):
    monkeypatch.setattr('builder.docker._is_inside_container', lambda: False)
    monkeypatch.setattr(DockerRunner, 'environment_identity', lambda self: 'sha256:test-image')


def command(runner, **kwargs):
    with patch('subprocess.run', return_value=MagicMock(returncode=0)) as call:
        runner.run(['true'], **kwargs)
    return call.call_args.args[0], call.call_args.kwargs


def mounts(cmd):
    return [cmd[index + 1] for index, value in enumerate(cmd) if value == '-v']


def test_工具与外部目录同绝对路径挂载(host, tmp_path):
    tool, app = tmp_path / 'tool', tmp_path / 'external app'
    tool.mkdir()
    app.mkdir()
    cmd, _ = command(DockerRunner(tool), extra_mounts=[app], cwd=str(app))
    assert f'{tool}:{tool}:rw' in mounts(cmd)
    assert f'{app}:{app}:rw' in mounts(cmd)
    assert cmd[cmd.index('-w') + 1] == str(app)
    assert 'FLANGE_BUILD_ENVIRONMENT=sha256:test-image' in cmd
    assert f'PYTHONPATH={tool}' in cmd
    assert cmd[cmd.index('--progress') + 1] == 'quiet'


def test_父目录覆盖子目录并解析符号链接(host, tmp_path):
    nested = tmp_path / 'app'
    nested.mkdir()
    link = tmp_path / 'alias'
    link.symlink_to(nested)
    cmd, _ = command(DockerRunner(tmp_path), extra_mounts=[link, nested])
    assert mounts(cmd) == [f'{tmp_path}:{tmp_path}:rw']


def test_任意产物根可挂载且管道关闭TTY(host, tmp_path, monkeypatch):
    tool, workspace = tmp_path / 'tool', tmp_path / 'workspace'
    tool.mkdir()
    workspace.mkdir()
    context = WorkspaceContext(tool, workspace, tmp_path / 'outputs', Target('b', 'p', 'debug'))
    monkeypatch.setattr('sys.stdout.isatty', lambda: False)
    cmd, kwargs = command(DockerRunner(context=context))
    assert f'{context.build_root}:{context.build_root}:rw' in mounts(cmd)
    assert '-T' in cmd
    assert kwargs['stdout'] is not None


def test_容器内不嵌套Docker(tmp_path, monkeypatch):
    monkeypatch.setattr('builder.docker._is_inside_container', lambda: True)
    cmd, _ = command(DockerRunner(tmp_path), extra_mounts=[tmp_path])
    assert cmd == ['true']


@pytest.mark.parametrize('privileged', [False, True])
@pytest.mark.parametrize('inherited', ['false', 'true'])
def test_特权由Compose服务配置按次设置而非run参数(host, tmp_path, monkeypatch, privileged, inherited):
    monkeypatch.setenv('FLANGE_BUILD_PRIVILEGED', inherited)
    cmd, kwargs = command(DockerRunner(tmp_path), privileged=privileged)
    assert '--privileged' not in cmd
    assert kwargs['env']['FLANGE_BUILD_PRIVILEGED'] == ('true' if privileged else 'false')
    assert kwargs['env']['FLANGE_BUILD_IMAGE'] == 'sha256:test-image'
    assert os.environ['FLANGE_BUILD_PRIVILEGED'] == inherited
