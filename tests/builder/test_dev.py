"""资源 CLI 的结构化结果、外部上下文及 Package 动作契约。"""
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from tests.builder.app_support import app, builder
from builder import dev
from builder.app_spec import load_spec
from builder.package_build import PackageBuilder
from builder.presentation import UsageError


def test_create_uses_external_invocation_and_target_architecture(tmp_path, monkeypatch):
    engine = builder(tmp_path, arch='armhf')
    monkeypatch.setattr(dev, 'resolve_config', lambda context: engine._config)
    result = dev.execute(['app', 'create', 'hello', '--build-system', 'make'], context=engine.context)
    assert Path(result['path']) == engine.context.workspace_root / 'hello'
    assert load_spec(Path(result['path'])).app.arch == ['armhf']


def test_create_without_target_uses_cwd_and_arch_override(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = dev.execute(['app', 'create', 'hello', '--arch', 'armhf'])
    assert load_spec(Path(result['path'])).app.arch == ['armhf']


def test_invalid_option_raises_usage_error_for_json_envelope():
    with pytest.raises(UsageError, match='froce'):
        dev.execute(['app', 'build', '--froce'])


def test_plan_uses_readonly_resolution(tmp_path, monkeypatch):
    source = app(tmp_path / 'hello')
    engine = builder(tmp_path)
    engine._source.locate_app = lambda *args: source
    engine._source.ensure_app = lambda *args: pytest.fail('plan不能准备源码')
    monkeypatch.setattr(dev, '_builder', lambda *args: engine)
    monkeypatch.setattr(dev, 'resolve_config', lambda context: engine._config)
    result = dev.execute(['app', 'plan', 'hello'], context=engine.context)
    assert len(result['plans']) == 1
    assert not engine.context.build_root.exists()


def test_host_handoff_freezes_full_closure_and_returns_this_build_status(tmp_path, monkeypatch):
    dep = app(tmp_path / 'outside/dep')
    main = app(tmp_path / 'outside/main', deps=['dep'])
    engine = builder(tmp_path, apps={'main': main, 'dep': dep})
    monkeypatch.setattr(dev, '_builder', lambda *args: engine)
    calls = []
    def docker_run(argv, **kwargs):
        calls.append((argv, kwargs))
        payload = json.loads(Path(argv[-1]).read_text())
        assert set(payload['context']['apps']) == {'main', 'dep'}
        dev._internal_build(Path(argv[-1]))
        return subprocess.CompletedProcess(argv, 0)
    runner = MagicMock()
    runner.context = engine.context
    runner.run.side_effect = docker_run
    monkeypatch.setattr(dev, 'DockerRunner', lambda **kwargs: runner)
    report = dev.build_report(engine.context, ['main'], config=engine._config)
    assert all(not item.reused for item in report.ordered)
    assert set(calls[0][1]['extra_mounts']) == {main, dep}
    assert list((engine.context.build_root / 'requests').iterdir()) == []


def test_custom_test_keeps_argv_and_records_failure_without_adb(tmp_path):
    source = app(tmp_path / 'hello')
    engine = builder(tmp_path, apps={'hello': source})
    report = engine.build_one('hello')
    result = dev._action(['python3', '-c', 'import sys; print(sys.argv[1]); sys.exit(4)'],
                         ['one argument; literal'], source, engine.context, report, 'test', None, 5)
    assert result['exit_code'] == 4 and result['status'] == 'failed'
    assert result['stdout'] == 'one argument; literal\n'
    assert result['device']['transport'] == 'action'
    assert result['artifact_identity'] == report.identity


def test_actions_only_package_build_publish_then_test(tmp_path, monkeypatch):
    engine = builder(tmp_path)
    directory = tmp_path / 'sdk'
    directory.mkdir()
    package = {'name': 'sdk', 'components': [], 'actions': {
        'build': ['python3', 'compile.py'],
        'test': ['python3', '-c', 'import os; from pathlib import Path; assert (Path(os.environ["FLANGE_TARGET_DIR"])/"sdk.bin").read_text()=="sdk"'],
    }}
    (directory / 'package.py').write_text('PACKAGE = ' + repr(package))
    runner = MagicMock()
    runner.context = engine.context
    def compile_package(argv, **options):
        if argv[:4] == ['python3', '-m', 'builder.dev', '_build-package']:
            dev._internal_package_build(Path(argv[-1]))
            return subprocess.CompletedProcess(argv, 0)
        assert argv == ['python3', 'compile.py']
        assert Path(options['cwd']) != directory
        (Path(options['env']['FLANGE_PACKAGE_OUTPUT_DIR']) / 'sdk.bin').write_text('sdk')
    runner.run.side_effect = compile_package
    monkeypatch.setattr(dev, 'DockerRunner', lambda **kwargs: runner)
    monkeypatch.setattr(dev, 'resolve_config', lambda context: engine._config)
    built = dev.execute(['package', 'build', str(directory)], context=engine.context)
    assert Path(built['manifest_path']).is_file()
    result = dev.execute(['package', 'test', str(directory), '--no-build'], context=engine.context)
    assert result['exit_code'] == 0 and result['artifact_identity'] == built['identity']
    assert runner.run.call_count == 2


def test_package_missing_declared_output_cannot_report_success(tmp_path):
    engine = builder(tmp_path)
    directory = tmp_path / 'sdk'
    directory.mkdir()
    (directory / 'package.py').write_text('PACKAGE = {}')
    package = {'name': 'sdk', 'components': [], 'actions': {'build': ['true']}}
    with pytest.raises(ValueError, match='空|empty'):
        PackageBuilder(engine.context, MagicMock()).build(directory, package)


def test_host_detected_corruption_forces_container_even_with_stale_mount_metadata(tmp_path, monkeypatch):
    source = app(tmp_path / 'hello')
    engine = builder(tmp_path, apps={'hello': source})
    initial = engine.build_one('hello')
    initial.runtime_debs[0].chmod(0o600)
    monkeypatch.setattr(dev, '_builder', lambda *args: engine)
    runner = MagicMock()
    runner.context = engine.context
    def run(argv, **options):
        payload = json.loads(Path(argv[-1]).read_text())
        assert payload['force'] is True
        # 模拟容器收到请求前共享目录权限恢复成旧的可命中视图。
        initial.runtime_debs[0].chmod(0o644)
        dev._internal_build(Path(argv[-1]))
        return subprocess.CompletedProcess(argv, 0)
    runner.run.side_effect = run
    monkeypatch.setattr(dev, 'DockerRunner', lambda **kwargs: runner)
    result = dev.build_report(engine.context, ['hello'], config=engine._config)
    assert not result.root().reused
    assert result.validate()


def test_package_list_reports_packages_instead_of_apps(tmp_path, monkeypatch):
    engine = builder(tmp_path)
    directory = engine.context.workspace_root / 'sdk'
    directory.mkdir()
    (directory / 'package.py').write_text("PACKAGE = {'name': 'sdk', 'components': [], 'actions': {'build': ['true']}}")
    monkeypatch.setattr(dev, 'resolve_config', lambda context: engine._config)
    result = dev.execute(['package', 'list'], context=engine.context)
    assert 'apps' not in result
    assert result['packages'][0]['name'] == 'sdk'
