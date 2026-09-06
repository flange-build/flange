"""独立资源构建的输出级别、日志轮转与异常收尾。"""
from pathlib import Path
import pytest
from tests.builder.app_support import builder
from builder.development_output import run_logged
from builder import dev


@pytest.mark.parametrize('level,visible', [('normal', False), ('quiet', False), ('verbose', True)])
def test_raw_output_always_logged_and_only_verbose_echoes(tmp_path, capsys, level, visible):
    engine = builder(tmp_path)
    def execute(output):
        output.feed_line('compiler-raw-output\n')
        return 'result'
    assert run_logged(engine.context, engine._config, 'app', level, execute) == 'result'
    printed = capsys.readouterr().out
    assert ('compiler-raw-output' in printed) is visible
    log = (engine.context.target_dir / 'build.log').read_text()
    assert 'compiler-raw-output' in log and '构建完成' in log
    assert '构建失败' not in log
    assert '\x1b[' not in log


def test_log_rotation_keeps_previous_build(tmp_path):
    engine = builder(tmp_path)
    for value in ['first-compiler-output', 'second-compiler-output']:
        run_logged(engine.context, engine._config, 'app', 'quiet', lambda output: output.feed_line(value))
    assert 'first-compiler-output' in (engine.context.target_dir / 'build.log.1').read_text()
    assert 'second-compiler-output' in (engine.context.target_dir / 'build.log').read_text()


@pytest.mark.parametrize('failure,status', [
    (RuntimeError('编译失败'), '构建失败'),
    (KeyboardInterrupt(), '构建已取消'),
])
def test_failure_and_cancellation_close_log_and_never_report_success(tmp_path, failure, status):
    engine = builder(tmp_path)
    outputs = []
    def execute(output):
        outputs.append(output)
        output.feed_line('last compiler diagnostic')
        raise failure
    with pytest.raises(type(failure)):
        run_logged(engine.context, engine._config, 'package', 'normal', execute)
    assert outputs[0]._log_file.closed
    log = (engine.context.target_dir / 'build.log').read_text()
    assert status in log and 'last compiler diagnostic' in log
    assert '构建完成' not in log
    if isinstance(failure, KeyboardInterrupt):
        assert '构建失败' not in log


def test_internal_main_does_not_duplicate_report_json(monkeypatch, capsys):
    monkeypatch.setattr(dev, '_internal_build', lambda path: {'identity': 'artifact-identity'})
    assert dev.main(['_build-app', '/unused/request.json']) == 0
    assert capsys.readouterr().out == ''


@pytest.mark.parametrize('resource', ['app', 'package'])
def test_resource_build_output_flags_are_explicit_and_mutually_exclusive(resource):
    from builder.presentation import UsageError
    verbose = dev._parser().parse_args([resource, 'build', '.', '-v'])
    quiet = dev._parser().parse_args([resource, 'build', '.', '-q'])
    assert dev._output_level(verbose) == 'verbose'
    assert dev._output_level(quiet) == 'quiet'
    with pytest.raises(UsageError):
        dev._parser().parse_args([resource, 'build', '.', '-v', '-q'])
