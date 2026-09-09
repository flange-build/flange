"""离线容器首启导入须可恢复租约丢失，且不能绕过内容校验。"""

import hashlib
import json
from pathlib import Path
import runpy
import subprocess

import pytest


RUNTIME = Path(__file__).resolve().parents[1] / (
    'components/packages/arduino-unoq-runtime/rootfs/usr/lib/flange/unoq')
LEASE_ERROR = 'failed to ingest "json": commit failed: lease does not exist: not found\n'


@pytest.fixture
def loader(monkeypatch):
    monkeypatch.syspath_prepend(str(RUNTIME))
    return runpy.run_path(str(RUNTIME / 'load-containers'))['main'].__globals__


@pytest.mark.parametrize('failure', [LEASE_ERROR, 'no space left on device\n', 'invalid tar header\n'])
def test_import_retries_only_missing_lease_once(loader, monkeypatch, capsys, failure):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1 if len(calls) == 1 else 0,
                                           failure if len(calls) == 1 else 'Loaded image: test\n')

    monkeypatch.setattr(subprocess, 'run', run)
    if failure == LEASE_ERROR:
        loader['load_archive'](Path('/test.tar.gz'))
        assert calls == [['docker', 'load', '--input', '/test.tar.gz']] * 2
    else:
        with pytest.raises(subprocess.CalledProcessError) as error:
            loader['load_archive'](Path('/test.tar.gz'))
        assert error.value.output == failure
        assert len(calls) == 1
    assert failure in capsys.readouterr().out


def test_persistent_missing_lease_remains_failure(loader, monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1, LEASE_ERROR)

    monkeypatch.setattr(subprocess, 'run', run)
    with pytest.raises(subprocess.CalledProcessError):
        loader['load_archive'](Path('/test.tar.gz'))
    assert len(calls) == 2


@pytest.mark.parametrize('synchronized_at', [0, 2, None])
def test_wait_is_bounded_by_monotonic_clock(loader, monkeypatch, tmp_path, synchronized_at):
    elapsed = [0.0]
    marker = tmp_path / 'synchronized'
    if synchronized_at == 0:
        marker.touch()

    def sleep(seconds):
        elapsed[0] += seconds
        if synchronized_at is not None and elapsed[0] >= synchronized_at:
            marker.touch()

    monkeypatch.setattr(loader['time'], 'monotonic', lambda: elapsed[0])
    monkeypatch.setattr(loader['time'], 'sleep', sleep)
    # 校时可任意改变墙钟；等待上限只能使用单调时钟。
    monkeypatch.setattr(loader['time'], 'time', lambda: pytest.fail('不应读取墙钟'))
    loader['wait_for_time_sync'](timeout=3, marker=marker)
    assert elapsed[0] == (3 if synchronized_at is None else synchronized_at)


@pytest.fixture
def runtime_tree(tmp_path):
    home = tmp_path / 'home'
    resources = tmp_path / 'resources'
    cache = home / '.cache/flange-containers'
    cache.mkdir(parents=True)
    resources.mkdir()
    (home / '.arduino15').mkdir()
    (home / '.arduino15/flange-environment.lock.json').write_text('{}')
    (resources / 'environment.lock.json').write_text('{}')
    images = []
    for number in range(5):
        item = {
            'tag': f'example/image-{number}:1.0',
            'image': f'example/image-{number}@sha256:' + str(number) * 64,
            'config_digest': 'sha256:' + str(number) * 64,
            'archive': f'image-{number}.tar.gz',
        }
        archive = cache / item['archive']
        content = f'离线归档 {number}'.encode()
        archive.write_bytes(content)
        archive.with_suffix('.sha256').write_text(hashlib.sha256(content).hexdigest())
        images.append(item)
    lock = json.dumps({'images': images})
    (cache / 'containers.lock.json').write_text(lock)
    (resources / 'containers.lock.json').write_text(lock)
    assets = home / '.local/share/arduino-app-cli/assets/0.12.0'
    assets.mkdir(parents=True)
    compose = assets / 'compose.yaml'
    compose.write_text('services:\n' + ''.join(
        f'  image-{n}:\n    image: {item["image"]}\n' for n, item in enumerate(images)))
    return home, resources, images, compose


def test_partial_first_boot_recovers_and_second_run_is_idempotent(
    loader, monkeypatch, runtime_tree,
):
    home, resources, images, compose = runtime_tree
    loaded = {item['tag']: item for item in images[:2]}
    imports = []
    waits = []
    monkeypatch.setitem(loader, 'wait_for_time_sync', lambda: waits.append(True))

    def inspect(tag):
        item = loaded[tag]
        return json.dumps([{'Id': item['config_digest'], 'Architecture': 'arm64', 'Os': 'linux'}])

    def run(command, **kwargs):
        if command[:3] == ['docker', 'image', 'inspect']:
            return subprocess.CompletedProcess(command, 0, inspect(command[-1])) \
                if command[-1] in loaded else subprocess.CompletedProcess(command, 1, '')
        if command[:3] == ['docker', 'load', '--input']:
            imports.append(command[-1])
            if len(imports) == 1:
                return subprocess.CompletedProcess(command, 1, LEASE_ERROR)
            item = next(item for item in images if item['archive'] == Path(command[-1]).name)
            loaded[item['tag']] = item
            return subprocess.CompletedProcess(command, 0, 'Loaded image\n')
        assert command[0] == 'chown'
        return subprocess.CompletedProcess(command, 0, '')

    monkeypatch.setattr(subprocess, 'run', run)
    monkeypatch.setattr(subprocess, 'check_output', lambda command: inspect(command[-1]))
    loader['main'](home, resources)
    assert len(imports) == 4
    assert imports[0] == imports[1]
    assert waits == [True]
    assert len(loaded) == 5
    for item in images:
        assert 'image: ' + item['config_digest'] in compose.read_text()
    loader['main'](home, resources)
    assert len(imports) == 4
    assert waits == [True]


@pytest.mark.parametrize('damage', ['environment', 'archive', 'identity'])
def test_import_failures_do_not_publish_compose(loader, monkeypatch, runtime_tree, damage):
    home, resources, images, compose = runtime_tree
    original = compose.read_bytes()
    if damage == 'environment':
        (resources / 'environment.lock.json').write_text('{"changed": true}')
    elif damage == 'archive':
        (home / '.cache/flange-containers' / images[0]['archive']).write_bytes(b'corrupt')
    imports = []
    monkeypatch.setitem(loader, 'wait_for_time_sync', lambda: None)
    monkeypatch.setitem(loader, 'load_archive', lambda archive: imports.append(archive))
    monkeypatch.setattr(subprocess, 'run', lambda command, **kwargs:
                        subprocess.CompletedProcess(command, 1, ''))
    monkeypatch.setattr(subprocess, 'check_output', lambda command: json.dumps([
        {'Id': images[0]['config_digest'], 'Architecture': 'amd64', 'Os': 'linux'}]))
    with pytest.raises(SystemExit):
        loader['main'](home, resources)
    assert len(imports) == (1 if damage == 'identity' else 0)
    assert compose.read_bytes() == original
