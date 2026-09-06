"""App 缓存由声明输入和实际产物共同决定。"""
import os
from dataclasses import replace
from tests.builder.app_support import app, builder
from builder.app import AppBuilder
from builder.source import SourceManager
from builder.workspace import Target


def test_only_changed_independent_app_rebuilds(tmp_path):
    alpha, beta = app(tmp_path / 'alpha'), app(tmp_path / 'beta')
    engine = builder(tmp_path, apps={'alpha': alpha, 'beta': beta})
    engine.build(['alpha', 'beta'])
    (alpha / 'bin/alpha').write_text('#!/bin/sh\necho updated\n')
    report = engine.build(['alpha', 'beta'])
    assert [item.reused for item in report.ordered] == [False, True]


def test_dependency_output_change_rebuilds_consumer(tmp_path):
    dep = app(tmp_path / 'dep')
    main = app(tmp_path / 'main', deps=['dep'])
    engine = builder(tmp_path, apps={'main': main, 'dep': dep})
    first = engine.build_one('main')
    (dep / 'bin/dep').write_text('#!/bin/sh\necho dependency changed\n')
    second = engine.build_one('main')
    assert not any(item.reused for item in second.ordered)
    assert first.identity != second.identity


def test_content_and_permission_corruption_rebuild_every_declared_deb(tmp_path):
    source = app(tmp_path / 'demo', kind='lib')
    engine = builder(tmp_path, apps={'demo': source})
    first = engine.build_one('demo').root()
    debs = [artifact.path for artifact in first.manifest.artifacts if artifact.path.suffix == '.deb']
    for path in debs:
        path.unlink()
        assert not engine.build_one('demo').root().reused
    installed = first.install_dir / 'empty'
    installed.write_text('unrecorded')
    assert not engine.build_one('demo').root().reused
    debs[0].chmod(0o600)
    assert not engine.build_one('demo').root().reused


def test_actual_image_identity_invalidates_cache(tmp_path, monkeypatch):
    source = app(tmp_path / 'hello')
    engine = builder(tmp_path, apps={'hello': source})
    monkeypatch.setenv('FLANGE_ENVIRONMENT_PROVIDER', 'ubuntu')
    monkeypatch.setenv('FLANGE_BUILD_ENVIRONMENT', 'sha256:first')
    engine.build_one('hello')
    assert engine.build_one('hello').root().reused
    monkeypatch.setenv('FLANGE_ENVIRONMENT_PROVIDER', 'ubuntu')
    monkeypatch.setenv('FLANGE_BUILD_ENVIRONMENT', 'sha256:second')
    assert not engine.build_one('hello').root().reused


def test_source_build_directory_is_input_but_explicit_buildroot_is_not(tmp_path):
    engine = builder(tmp_path)
    source = app(engine.context.workspace_root / 'hello')
    engine.context = replace(engine.context, apps={'hello': source})
    from builder.app_resolver import AppResolver
    engine.resolver = AppResolver(engine.context, engine._source, engine._config)
    ordinary = source / 'build'
    ordinary.mkdir()
    (ordinary / 'input.txt').write_text('one')
    first = engine.plan([source])[0].fingerprint().digest
    (ordinary / 'input.txt').write_text('two')
    second = engine.plan([source])[0].fingerprint().digest
    assert first != second
    engine.context.build_root.mkdir()
    (engine.context.build_root / 'unrelated').write_text('generated')
    assert engine.plan([source])[0].fingerprint().digest == second


def test_target_variant_and_same_name_source_have_separate_outputs(tmp_path):
    first = app(tmp_path / 'one/hello')
    second = app(tmp_path / 'two/hello')
    engine = builder(tmp_path, apps={'hello': first})
    a, b = engine.build_one(first).root(), engine.build_one(second).root()
    assert a.resource_id != b.resource_id
    assert a.runtime_debs[0] != b.runtime_debs[0]
    context = replace(engine.context, target=Target('board', 'default', 'release'))
    other = AppBuilder(engine._docker, SourceManager(context=context), {**engine._config, "variant": "release"}, context=context)
    c = other.build_one(first).root()
    assert c.runtime_debs[0] != a.runtime_debs[0]
    assert a.validate() and b.validate() and c.validate()
