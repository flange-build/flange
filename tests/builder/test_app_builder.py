"""完整闭包、安装内容、架构和发布失败的行为回归。"""
from dataclasses import replace
import errno
import json
import os
from pathlib import Path
import shutil
import stat
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


def _linked_install_tree(directory, external):
    """先创建链接再物化目标，模拟动态库 install 的任意创建顺序。"""
    links = {
        "usr/lib/libdemo.so": "libdemo.so.1",
        "usr/lib/libdemo.so.1": "libdemo.so.1.2",
        "usr/lib/absolute.so": "/opt/flange-test-target/libdemo.so.9",
        "usr/lib/optional.so": "future-optional.so",
        "usr/share/config-link": "config",
        "usr/share/external-link": str(external),
    }
    for relative, target in links.items():
        link = directory / relative
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target)
    library = directory / "usr/lib/libdemo.so.1.2"
    library.write_bytes(b"library fixture")
    library.chmod(0o640)
    executable = directory / "usr/bin/demo-tool"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o751)
    config = directory / "usr/share/config"
    config.mkdir(mode=0o710)
    (config / "default.conf").write_text("enabled=true\n")
    empty = directory / "var/lib/demo/empty"
    empty.mkdir(parents=True)
    empty.chmod(0o750)
    return links


def _assert_linked_install_tree(directory, links):
    for relative, target in links.items():
        link = directory / relative
        assert link.is_symlink(), relative
        assert os.readlink(link) == target
    assert (directory / "usr/lib/libdemo.so").read_bytes() == b"library fixture"
    assert not (directory / "usr/lib/optional.so").exists()
    assert (directory / "usr/share/config-link/default.conf").read_text() == "enabled=true\n"
    assert stat.S_IMODE((directory / "usr/lib/libdemo.so.1.2").stat().st_mode) == 0o640
    assert stat.S_IMODE((directory / "usr/bin/demo-tool").stat().st_mode) == 0o751
    empty = directory / "var/lib/demo/empty"
    assert empty.is_dir() and not any(empty.iterdir())
    assert stat.S_IMODE(empty.stat().st_mode) == 0o750
    assert stat.S_IMODE((directory / "usr/share/config").stat().st_mode) == 0o710


def _restrict_shared_link_metadata(monkeypatch):
    """共享卷的链接元数据操作可能错误地访问尚不存在的目标。"""
    original = shutil.copystat

    def copystat(source, destination, *, follow_symlinks=True):
        destination = Path(destination)
        if Path(source).is_symlink() and destination.is_symlink() and not destination.exists():
            raise FileNotFoundError(errno.ENOENT, "共享卷无法复制悬空链接的扩展属性", str(destination))
        return original(source, destination, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(shutil, "copystat", copystat)


@pytest.mark.parametrize("limited_metadata", [False, True])
def test_App_staging发布保留符号链接与权限且可以复用(tmp_path, monkeypatch, limited_metadata):
    source = app(tmp_path / "sdk", kind="staging", system="custom",
                 build={"staging": "stage", "commands": [["produce-stage"]]})
    external = tmp_path / "external-config"
    external.mkdir()
    (external / "sentinel").write_text("宿主目录不能被解引用复制")
    engine = builder(tmp_path, apps={"sdk": source}, variant="release")
    links = {}

    def execute(command, **options):
        assert command == ["produce-stage"]
        staged = Path(options["env"]["FLANGE_APP_WORK_DIR"]) / "stage"
        links.update(_linked_install_tree(staged, external))

    engine._docker.run.side_effect = execute
    if limited_metadata:
        _restrict_shared_link_metadata(monkeypatch)
    report = engine.build_one("sdk")
    result = report.root()
    _assert_linked_install_tree(result.install_dir, links)
    assert report.validate() and result.manifest.validate()
    assert not result.reused
    reused = engine.build_one("sdk")
    assert reused.root().reused and reused.validate()
    assert reused.identity == report.identity
    assert engine._docker.run.call_count == 1
    assert (external / "sentinel").read_text() == "宿主目录不能被解引用复制"


@pytest.mark.parametrize("limited_metadata", [False, True])
def test_App编译与调试源码快照保留链接原文(tmp_path, monkeypatch, limited_metadata):
    source = app(tmp_path / "sdk", kind="staging", system="custom",
                 build={"staging": "stage", "commands": [["produce-stage"]]})
    external = tmp_path / "external-config"
    external.mkdir()
    links = _linked_install_tree(source / "fixtures", external)
    engine = builder(tmp_path, apps={"sdk": source}, variant="debug")

    def execute(command, **options):
        assert command == ["produce-stage"]
        compiled = Path(options["cwd"])
        assert compiled != source
        _assert_linked_install_tree(compiled / "fixtures", links)
        staged = Path(options["env"]["FLANGE_APP_WORK_DIR"]) / "stage"
        staged.mkdir()
        (staged / "sdk.bin").write_bytes(b"staging fixture")

    engine._docker.run.side_effect = execute
    if limited_metadata:
        _restrict_shared_link_metadata(monkeypatch)
    report = engine.build_one("sdk")
    result = report.root()
    _assert_linked_install_tree(Path(result.compile_source_dir) / "fixtures", links)
    _assert_linked_install_tree(Path(result.debug_source_dir) / "fixtures", links)
    _assert_linked_install_tree(source / "fixtures", links)
    assert report.validate() and result.manifest.validate()
    reused = engine.build_one("sdk")
    assert reused.root().reused and reused.validate()
    assert reused.identity == report.identity
    assert engine._docker.run.call_count == 1


@pytest.mark.parametrize("failure_kind", ["file", "directory_metadata"])
def test_App_staging实际复制失败保留上次成功产物(tmp_path, monkeypatch, failure_kind):
    source = app(tmp_path / "sdk", kind="staging", system="custom",
                 build={"staging": "stage", "commands": [["produce-stage"]]})
    source_input = source / "input.txt"
    source_input.write_text("first build")
    external = tmp_path / "external-config"
    external.mkdir()
    engine = builder(tmp_path, apps={"sdk": source}, variant="release")
    stage_directories = []

    def execute(command, **options):
        assert command == ["produce-stage"]
        staged = Path(options["env"]["FLANGE_APP_WORK_DIR"]) / "stage"
        stage_directories.append(staged)
        _linked_install_tree(staged, external)
        (staged / "usr/lib/libdemo.so.1.2").write_text(source_input.read_text())

    engine._docker.run.side_effect = execute
    previous = engine.build_one("sdk")
    original = previous.root()
    manifest_bytes = original.manifest_path.read_bytes()
    source_input.write_text("second build must not replace the first")
    copy_operation = shutil.copy2 if failure_kind == "file" else shutil.copystat

    def fail_copy(source_path, destination, *args, **kwargs):
        source_path = Path(source_path)
        expected_name = "libdemo.so.1.2" if failure_kind == "file" else "empty"
        if source_path.name == expected_name and source_path.is_relative_to(stage_directories[-1]):
            raise OSError(errno.EIO, "模拟共享卷真实读写故障", str(destination))
        return copy_operation(source_path, destination, *args, **kwargs)

    monkeypatch.setattr(shutil, "copy2" if failure_kind == "file" else "copystat", fail_copy)
    with pytest.raises(OSError, match="真实读写故障"):
        engine.build_one("sdk")
    assert original.manifest_path.read_bytes() == manifest_bytes
    assert (original.install_dir / "usr/lib/libdemo.so").read_text() == "first build"
    assert original.manifest.validate() and previous.validate()
    recorded = AppBuildReport.load(engine.report_path(previous.roots))
    assert recorded.identity == previous.identity and recorded.validate()
