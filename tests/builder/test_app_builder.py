"""完整闭包、安装内容、架构和发布失败的行为回归。"""
from dataclasses import replace
import json
from unittest.mock import patch
import pytest
from tests.builder.app_support import app, builder
from builder.app_model import AppBuildReport
from builder.app_build import validate_elf_architecture
from builder.artifacts import ArtifactManifest


def test_standalone_closure_builds_unselected_dependency_and_exact_runtime(tmp_path):
    dep = app(tmp_path / 'deps' / 'library', kind='vendor', install={'header.h': '/usr/include/demo.h'})
    (dep / 'header.h').write_text('int demo(void);')
    root = app(tmp_path / 'apps' / 'hello', deps=['library'])
    engine = builder(tmp_path, apps={'hello': root, 'library': dep})
    report = engine.build_one('hello')
    assert [item.name for item in report.ordered] == ['library', 'hello']
    assert len(report.runtime_debs) == 2
    assert report.root().dependency_ids == (report.ordered[0].resource_id,)
    assert report.runtime_debs_for(['hello']) == report.runtime_debs
    assert report.runtime_debs_for(['library']) == report.ordered[0].runtime_debs
    assert report.validate()
    loaded = AppBuildReport.load(engine.report_path(report.roots))
    assert not any(item.reused for item in loaded.ordered)
    assert all(item.reused for item in engine.build_one(root).ordered)


def test_cycle_and_missing_dependency_fail_before_execution(tmp_path):
    alpha = app(tmp_path / 'alpha', deps=['beta'])
    beta = app(tmp_path / 'beta', deps=['alpha'])
    engine = builder(tmp_path, apps={'alpha': alpha, 'beta': beta})
    with pytest.raises(ValueError, match='循环依赖'):
        engine.build_one('alpha')
    app(beta, deps=['missing'])
    with pytest.raises((ValueError, FileNotFoundError), match='missing'):
        engine.build_one('alpha')
    engine._docker.run.assert_not_called()


def test_failure_preserves_published_manifest_and_packages(tmp_path):
    source = app(tmp_path / 'hello')
    engine = builder(tmp_path, apps={'hello': source})
    old = engine.build_one('hello').root()
    old_bytes = old.runtime_debs[0].read_bytes()
    (source / 'bin/hello').write_text('#!/bin/sh\necho changed\n')
    with patch.object(ArtifactManifest, 'capture', side_effect=ValueError('发布故障')):
        with pytest.raises(ValueError, match='发布故障'):
            engine.build_one('hello')
    assert old.manifest.validate()
    assert old.runtime_debs[0].read_bytes() == old_bytes


def test_plan_is_read_only_and_does_not_fetch(tmp_path):
    source = app(tmp_path / 'hello')
    engine = builder(tmp_path)
    engine._source.locate_app = lambda name, config: source
    engine._source.ensure_app = lambda *args: pytest.fail('只读计划不能下载源码')
    plans = engine.plan(['hello'])
    assert len(plans) == 1
    assert not engine.context.build_root.exists()


def test_invalid_runtime_and_architecture_refuse_success(tmp_path):
    source = app(tmp_path / 'hello', runtime={'executable': '/opt/missing'})
    engine = builder(tmp_path, apps={'hello': source})
    with pytest.raises(ValueError, match='运行入口'):
        engine.build_one('hello')
    app(source, arch='armhf')
    with pytest.raises(ValueError, match='未声明支持架构'):
        engine.build_one('hello')


def test_linux_elf_checks_class_and_machine_but_firmware_has_own_arch(tmp_path):
    binary = tmp_path / 'elf'
    header = bytearray(20)
    header[:6] = b'\x7fELF\x02\x01'
    header[18:20] = (62).to_bytes(2, 'little')
    binary.write_bytes(header)
    with pytest.raises(ValueError, match='ELF 架构'):
        validate_elf_architecture([(binary, '/usr/bin/hello', 0o755)], 'aarch64')
    validate_elf_architecture([(binary, '/lib/firmware/aux.bin', 0o644)], 'aarch64')


def test_debug_source_is_immutable_and_manifested(tmp_path):
    source = app(tmp_path / 'hello')
    engine = builder(tmp_path, apps={'hello': source})
    report = engine.build_one('hello')
    result = report.root()
    from pathlib import Path
    before = (Path(result.debug_source_dir) / 'bin/hello').read_text()
    (source / 'bin/hello').write_text('#!/bin/sh\necho edited\n')
    assert (Path(result.debug_source_dir) / 'bin/hello').read_text() == before
    assert result.validate()
    assert result.compile_source_dir == str(source)


def test_report_metadata_tampering_is_rejected(tmp_path):
    source = app(tmp_path / 'hello')
    engine = builder(tmp_path, apps={'hello': source})
    report = engine.build_one('hello')
    path = engine.report_path(report.roots)
    content = json.loads(path.read_text())
    content['ordered'][0]['executable'] = '/usr/bin/other'
    path.write_text(json.dumps(content))
    with pytest.raises(ValueError, match='校验失败'):
        AppBuildReport.load(path)


def test_library_dev_package_and_runtime_are_separate(tmp_path):
    source = app(tmp_path / 'demo', kind='lib')
    (source / 'include').mkdir()
    (source / 'include/demo.h').write_text('int demo(void);')
    (source / 'lib').mkdir()
    (source / 'lib/libdemo.so').write_text('library fixture')
    engine = builder(tmp_path, apps={'demo': source})
    result = engine.build_one('demo').root()
    debs = [item.path for item in result.manifest.artifacts if item.path.suffix == '.deb']
    assert len(debs) == 2
    assert len(result.runtime_debs) == 1
    assert '-dev_' not in result.runtime_debs[0].name


def test_direct_api_rejects_config_context_target_mismatch(tmp_path):
    from builder.app import AppBuilder
    engine = builder(tmp_path)
    with pytest.raises(ValueError, match='WorkspaceContext 不匹配'):
        AppBuilder(engine._docker, engine._source, {**engine._config, 'board': 'other'}, context=engine.context)


def test_report_cannot_relabel_existing_artifacts_as_another_target(tmp_path):
    source = app(tmp_path / 'hello')
    engine = builder(tmp_path, apps={'hello': source})
    report = engine.build_one('hello')
    forged = replace(report, target={**report.target, 'board': 'other'})
    assert not forged.validate()
    assert not replace(report, architecture='armhf').validate()


@pytest.mark.parametrize("level,visible", [("normal", False), ("quiet", False), ("verbose", True)])
def test_App资源身份始终写日志而仅在详细模式展示(tmp_path, capsys, level, visible):
    from builder.development_output import run_logged

    source = app(tmp_path / "hello")
    engine = builder(tmp_path, apps={"hello": source})

    def execute(output):
        engine.output = output
        return engine.build_one("hello")

    result = run_logged(engine.context, engine._config, "app", level, execute).root()
    assert (result.resource_id in capsys.readouterr().out) is visible
    log = (engine.context.target_dir / "build.log").read_text()
    assert result.resource_id in log
