"""设备流程通过可控传输验证，不接触任何真实设备。"""
import json
import subprocess
from hashlib import sha256
from pathlib import Path
import pytest
from tests.builder.app_support import app, builder
from builder import deploy


class FakeDevice:
    serial = 'fixture-device'
    def __init__(self, *, architecture='arm64', code=0, timeout=False, bad_hash=False):
        self.architecture, self.code, self.timeout, self.bad_hash = architecture, code, timeout, bad_hash
        self.calls, self.uploads = [], {}
    def push(self, source, destination):
        self.calls.append(('push', str(source), destination))
        self.uploads[destination] = Path(source)
    def shell(self, argv, **options):
        self.calls.append(('shell', argv, options))
        output, code = '', 0
        if argv == ['dpkg', '--print-architecture']:
            output = self.architecture + '\n'
        elif argv[0] == 'sha256sum':
            output = ('bad' if self.bad_hash else sha256(self.uploads[argv[1]].read_bytes()).hexdigest()) + '  file\n'
        elif argv[0].startswith('/usr/bin/'):
            if self.timeout:
                raise subprocess.TimeoutExpired(argv, options.get('timeout'))
            code, output = self.code, '测试输出\n'
        elif argv[:2] == ['systemctl', 'show']:
            output = '42\n'
        return subprocess.CompletedProcess(argv, code, output, '测试诊断\n' if code else '')


def _built(tmp_path, **options):
    source = app(tmp_path / 'hello', **options)
    engine = builder(tmp_path, apps={'hello': source})
    return engine, engine.build_one('hello')


def test_architecture_mismatch_before_any_upload_and_failure_record(tmp_path):
    engine, report = _built(tmp_path)
    device = FakeDevice(architecture='armhf')
    with pytest.raises(deploy.DeployError, match='设备架构'):
        deploy.operate_report(engine.context, report, 'deploy', transport=device)
    assert not device.uploads
    sessions = list((engine.context.target_dir / 'sessions').glob('*/session.json'))
    record = json.loads(sessions[0].read_text())
    assert record['status'] == 'failed' and record['artifact_identity'] == report.identity


def test_corrupted_local_artifact_rejects_before_device_contact(tmp_path):
    engine, report = _built(tmp_path)
    report.runtime_debs[0].write_text('broken')
    device = FakeDevice()
    with pytest.raises(deploy.DeployError, match='产物校验失败'):
        deploy.operate_report(engine.context, report, 'deploy', transport=device)
    assert device.calls == []


def test_remote_hash_failure_never_runs_dpkg_and_cleans_staging(tmp_path):
    engine, report = _built(tmp_path)
    device = FakeDevice(bad_hash=True)
    with pytest.raises(deploy.DeployError, match='内容校验失败'):
        deploy.operate_report(engine.context, report, 'deploy', transport=device)
    commands = [call[1] for call in device.calls if call[0] == 'shell']
    assert not any(command[:2] == ['dpkg', '-i'] for command in commands)
    assert commands[-1][:2] == ['rm', '-rf']


def test_deployment_installs_exact_transitive_runtime_closure_once(tmp_path):
    dep = app(tmp_path / 'dep', kind='lib')
    main = app(tmp_path / 'main', deps=['dep'])
    engine = builder(tmp_path, apps={'main': main, 'dep': dep})
    report = engine.build_one('main')
    stray = engine.context.target_dir / 'unrelated.deb'
    stray.write_text('must not deploy')
    device = FakeDevice()
    result = deploy.operate_report(engine.context, report, 'deploy', transport=device)
    assert result['status'] == 'succeeded'
    assert set(device.uploads.values()) == set(report.runtime_debs)
    assert not any('-dev_' in path.name for path in device.uploads.values())
    installs = [call for call in device.calls if call[0] == 'shell' and call[1][:2] == ['dpkg', '-i']]
    assert len(installs) == 1 and len(installs[0][1]) == 4


@pytest.mark.parametrize('code,expected', [(0, 'passed'), (7, 'failed')])
def test_test_result_persists_exit_output_target_and_artifact(tmp_path, code, expected):
    engine, report = _built(tmp_path)
    result = deploy.operate_report(engine.context, report, 'test', args=['one argument'], transport=FakeDevice(code=code))
    assert result['status'] == expected and result['exit_code'] == code
    assert Path(result['test']['stdout_path']).read_text() == '测试输出\n'
    assert result['test']['command'] == ['/usr/bin/hello', 'one argument']
    assert json.loads(Path(result['report_path']).read_text())['artifact_identity'] == report.identity


def test_timeout_is_explicit_nonzero_record(tmp_path):
    engine, report = _built(tmp_path)
    result = deploy.operate_report(engine.context, report, 'test', timeout=1, transport=FakeDevice(timeout=True))
    assert result['status'] == 'timed_out' and result['exit_code'] == 124


def test_target_gdb_consumes_snapshot_and_compiler_path_mapping(tmp_path):
    engine, report = _built(tmp_path)
    device = FakeDevice()
    result = deploy.operate_report(engine.context, report, 'debug', transport=device)
    command = next(call[1] for call in device.calls if call[0] == 'shell' and call[1][0] == 'gdb' and '-ex' in call[1])
    assert f"set substitute-path {report.root().compile_source_dir} /tmp/flange-source-{result['id']}" in command
    assert Path(report.root().debug_source_dir) in device.uploads.values()
    assert result['debug']['source_mapping']
    assert device.calls[-1][1][:2] == ['rm', '-rf']


def test_noninteractive_debug_refuses_before_device_access(tmp_path, monkeypatch):
    engine, report = _built(tmp_path)
    monkeypatch.setenv('FLANGE_NO_INTERACTION', '1')
    device = FakeDevice()
    with pytest.raises(deploy.DeployError, match='交互终端'):
        deploy.operate_report(engine.context, report, 'debug', transport=device)
    assert not device.calls


def test_unsupported_runtime_refuses_before_deploy(tmp_path):
    engine, report = _built(tmp_path, kind='lib')
    device = FakeDevice()
    with pytest.raises(deploy.DeployError, match='运行入口'):
        deploy.operate_report(engine.context, report, 'run', transport=device)
    assert not device.calls


def test_multi_root_deploy_keeps_complete_request_identity(tmp_path):
    first, second = app(tmp_path / 'one'), app(tmp_path / 'two')
    engine = builder(tmp_path, apps={'one': first, 'two': second})
    report = engine.build(['one', 'two'])
    result = deploy.operate_report(engine.context, report, 'deploy', transport=FakeDevice())
    assert result['artifact_identity'] == report.identity


def test_adb_argv_preserves_spaces_and_shell_metacharacters():
    import shlex
    command = deploy._adb_shell_argv('serial', ['/usr/bin/demo', 'one argument', '$(id)', 'semi;colon'])
    assert shlex.split(command[-1]) == ['/usr/bin/demo', 'one argument', '$(id)', 'semi;colon']


def test_remote_gdb_waits_for_server_and_cleans_forward_on_debugger_failure(tmp_path, monkeypatch):
    engine, report = _built(tmp_path)
    monkeypatch.setattr(deploy.shutil, 'which', lambda name: '/usr/bin/gdb')
    commands = []
    server_state = {'terminated': False}
    class Server:
        def __init__(self, argv, stdout, **options):
            stdout.write('Listening on port 2345\n')
            stdout.flush()
        def poll(self):
            return None
        def terminate(self):
            server_state['terminated'] = True
        def wait(self, **options):
            return 0
    monkeypatch.setattr(deploy.subprocess, 'Popen', Server)
    def run(argv, **options):
        commands.append(argv)
        if argv[0] == '/usr/bin/gdb':
            assert str(report.root().install_dir / 'usr/bin/hello') in argv
            assert f'set substitute-path {report.root().compile_source_dir} {report.root().debug_source_dir}' in argv
            raise deploy.DeployError('调试器退出失败')
        return subprocess.CompletedProcess(argv, 0, '', '')
    monkeypatch.setattr(deploy, '_run_checked', run)
    with pytest.raises(deploy.DeployError, match='调试器退出失败'):
        deploy.operate_report(engine.context, report, 'debug', transport=FakeDevice(), debug_mode='remote')
    assert server_state['terminated']
    assert commands[-1] == ['adb', '-s', 'fixture-device', 'forward', '--remove', 'tcp:2345']
    record = json.loads(next((engine.context.target_dir / 'sessions').glob('*/session.json')).read_text())
    assert record['status'] == 'failed'
    assert record['debug']['server_log']


def test_service_test_restarts_published_service_before_checking_active(tmp_path):
    engine, report = _built(tmp_path, kind='service')
    device = FakeDevice()
    result = deploy.operate_report(engine.context, report, 'test', transport=device)
    commands = [call[1] for call in device.calls if call[0] == 'shell']
    restart = ['systemctl', 'restart', 'hello.service']
    active = ['systemctl', 'is-active', '--quiet', 'hello.service']
    assert commands.index(restart) < commands.index(active)
    assert result['status'] == 'passed'
    assert restart in result['test']['preparation_commands']
