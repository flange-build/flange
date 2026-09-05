"""原生工具链适配与隔离编译行为；真实交叉编译由 integration 矩阵覆盖。"""
import subprocess
from pathlib import Path
import pytest
from tests.builder.app_support import app, builder
from builder.app_spec import load_spec
from builder.scaffold import AppScaffold
from builder.toolchain import Toolchain


@pytest.mark.parametrize('arch,triple,family', [('aarch64', 'aarch64-linux-gnu', 'aarch64'), ('armhf', 'arm-linux-gnueabihf', 'arm')])
@pytest.mark.parametrize('system', ['cmake', 'meson', 'make'])
def test_generated_toolchain_uses_requested_target_and_isolated_paths(tmp_path, arch, triple, family, system):
    source = AppScaffold().create('hello', 'exec', system, parent_dir=tmp_path, arch=arch)
    spec = load_spec(source)
    toolchain = Toolchain.for_arch(arch)
    commands, install = toolchain.commands(spec, source=source, build=tmp_path / 'out/build',
                                          install=tmp_path / 'out/install', dependency_root=tmp_path / 'deps', variant='debug')
    flattened = ' '.join(value for command in commands for value in command)
    assert str(tmp_path / 'out/build') in flattened
    assert install
    if system == 'meson':
        text = (tmp_path / 'out/meson-cross.ini').read_text()
        assert f"cpu_family = '{family}'" in text
        assert f'{triple}-gcc' in text
        assert '--buildtype=debug' in flattened
    else:
        assert f'{triple}-gcc' in flattened
    if system == 'cmake':
        assert 'CMAKE_SYSROOT' not in flattened
        assert '-DCMAKE_BUILD_TYPE=Debug' in flattened
    if system == 'make':
        dry = subprocess.run(['make', '-n', *commands[0][1:]], cwd=source, text=True, capture_output=True, check=True)
        assert f'{triple}-gcc' in dry.stdout
        assert '-O0 -g' in dry.stdout
        assert not (source / 'build').exists()


def test_make_library_recipe_retains_required_pic_include_and_soname(tmp_path):
    source = AppScaffold().create('demo', 'lib', 'make', parent_dir=tmp_path)
    commands, _ = Toolchain.for_arch('aarch64').commands(load_spec(source), source=source, build=tmp_path / 'build',
                        install=tmp_path / 'install', dependency_root=tmp_path / 'deps', variant='release')
    result = subprocess.run(['make', '-n', *commands[0][1:]], cwd=source, text=True, capture_output=True, check=True)
    assert '-fPIC' in result.stdout and '-Iinclude' in result.stdout
    assert '-Wl,-soname,libdemo.so.1' in result.stdout


def test_make_compiles_snapshot_and_manifest_records_source_mapping(tmp_path):
    source = app(tmp_path / 'hello', system='make')
    (source / 'main.c').write_text('int main(void) { return 0; }')
    engine = builder(tmp_path, apps={'hello': source})
    def execute(argv, **options):
        cwd = Path(options['cwd'])
        assert cwd != source
        if argv[:2] == ['make', 'install']:
            target = Path(options['env']['DESTDIR']) / 'usr/bin/hello'
            target.parent.mkdir(parents=True)
            target.write_text('#!/bin/sh\nexit 0\n')
            target.chmod(0o755)
        else:
            (cwd / 'generated.o').write_bytes(b'object fixture')
    engine._docker.run.side_effect = execute
    result = engine.build_one('hello').root()
    assert not (source / 'generated.o').exists()
    assert result.compile_source_dir != str(source)
    assert (Path(result.debug_source_dir) / 'main.c').is_file()
    assert not (Path(result.debug_source_dir) / 'generated.o').exists()


def test_native_install_failure_never_publishes_success(tmp_path):
    source = app(tmp_path / 'hello', system='cmake')
    engine = builder(tmp_path, apps={'hello': source})
    def execute(argv, **options):
        if argv[:2] == ['cmake', '--install']:
            raise RuntimeError('install failed')
    engine._docker.run.side_effect = execute
    with pytest.raises(RuntimeError, match='install failed'):
        engine.build_one('hello')
    assert not list(engine.context.target_dir.rglob('manifest.json'))


def test_custom_build_action_is_consumed_and_apt_dependencies_are_deduplicated(tmp_path):
    source = app(tmp_path / 'hello', system='custom', actions={'build': ['python3', 'build.py']},
                 build={'commands': [['unused']], 'apt_packages': ['libdemo-dev:{arch}']})
    engine = builder(tmp_path, apps={'hello': source})
    calls = []
    def execute(argv, **options):
        calls.append(argv)
        if argv == ['python3', 'build.py']:
            target = Path(options['env']['DESTDIR']) / 'usr/bin/hello'
            target.parent.mkdir(parents=True)
            target.write_text('#!/bin/sh\nexit 0\n')
            target.chmod(0o755)
    engine._docker.run.side_effect = execute
    engine.build_one('hello')
    engine.build_one('hello', force=True)
    assert ['unused'] not in calls
    assert sum(argv[:2] == ['apt-get', 'update'] for argv in calls) == 1
    assert sum('libdemo-dev:arm64' in argv for argv in calls) == 1
