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


def test_容器跑完把宿主机要写的子树交还宿主机用户(host, tmp_path, monkeypatch):
    """容器内 root 落下的 locks/requests/target/work-apps 归还给宿主机用户，不动 sources/cache。"""
    tool, workspace = tmp_path / 'tool', tmp_path / 'workspace'
    tool.mkdir()
    workspace.mkdir()
    context = WorkspaceContext(tool, workspace, tmp_path / 'outputs', Target('b', 'p', 'debug'))
    for name in ('locks', 'requests', 'sources', 'cache', 'work/b-p-debug/apps',
                 'work/b-p-debug/rootfs', 'work/b-p-debug/packages'):
        (context.build_root / name).mkdir(parents=True)
    context.target_dir.mkdir(parents=True)
    monkeypatch.setattr('os.getuid', lambda: 1234)
    monkeypatch.setattr('os.getgid', lambda: 5678)
    with patch('subprocess.run', return_value=MagicMock(returncode=0)) as call:
        DockerRunner(context=context).run(['true'])
    assert call.call_count == 2
    chown = call.call_args_list[1].args[0]
    assert chown[chown.index('chown'):chown.index('1234:5678') + 1] == [
        'chown', '-R', '-h', '--from=0', '1234:5678'
    ]
    owned = set(chown[chown.index('1234:5678') + 1:])
    assert owned == {
        str(context.build_root / 'locks'),
        str(context.build_root / 'requests'),
        str(context.target_dir),
        str(context.build_root / 'work/b-p-debug/apps'),
        str(context.build_root / 'work/b-p-debug/packages'),
    }
    assert call.call_args_list[1].kwargs['env']['FLANGE_BUILD_PRIVILEGED'] == 'false'


def test_失败与只读查询不交还属主(host, tmp_path, monkeypatch):
    """构建失败也要交还（否则下一次锁就 EACCES）；只读查询不落目录也不 chown；root 无需交还。"""
    tool, workspace = tmp_path / 'tool', tmp_path / 'workspace'
    tool.mkdir()
    workspace.mkdir()
    context = WorkspaceContext(tool, workspace, tmp_path / 'outputs', Target('b', 'p', 'debug'))
    (context.build_root / 'locks').mkdir(parents=True)
    monkeypatch.setattr('os.getuid', lambda: 1234)
    with patch('subprocess.run', return_value=MagicMock(returncode=3)) as call:
        DockerRunner(context=context).run(['false'], check=False)
    assert call.call_count == 2 and 'chown' in call.call_args_list[1].args[0]
    with patch('subprocess.run', return_value=MagicMock(returncode=0)) as call:
        DockerRunner(context=context).run(['plan'], capture=True, ensure_build_root=False)
    assert call.call_count == 1
    monkeypatch.setattr('os.getuid', lambda: 0)
    with patch('subprocess.run', return_value=MagicMock(returncode=0)) as call:
        DockerRunner(context=context).run(['true'])
    assert call.call_count == 1
