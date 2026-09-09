"""Docker 存储后端变化不能放宽 config 摘要与平台验证。"""

import hashlib
import json
from pathlib import Path
import runpy
import subprocess

import pytest


MODULE = Path(__file__).resolve().parents[1] / (
    'components/packages/arduino-unoq-runtime/rootfs/usr/lib/flange/unoq/container_identity.py')
VERIFY = runpy.run_path(str(MODULE))['verified_image_id']
CONFIG = 'sha256:' + 'a' * 64


def test_classic_image_id():
    assert VERIFY({'Id': CONFIG, 'Architecture': 'arm64', 'Os': 'linux'}, CONFIG) == CONFIG
    assert VERIFY({'Id': CONFIG, 'Architecture': 'amd64', 'Os': 'linux'}, CONFIG) is None


@pytest.mark.parametrize('mismatch', ['none', 'config', 'content', 'platform'])
def test_containerd_manifest_is_verified(monkeypatch, mismatch):
    blob = json.dumps({'schemaVersion': 2, 'config': {'digest': CONFIG}}).encode()
    identity = 'sha256:' + hashlib.sha256(blob).hexdigest()
    inspect = {'Id': identity, 'Architecture': 'arm64', 'Os': 'linux',
               'Descriptor': {'digest': identity}}
    if mismatch == 'platform':
        inspect['Architecture'] = 'amd64'

    def run(argv, **kwargs):
        assert argv == ['ctr', '--namespace', 'moby', 'content', 'get', identity]
        return subprocess.CompletedProcess(argv, 0, blob + (b' ' if mismatch == 'content' else b''))

    monkeypatch.setattr(subprocess, 'run', run)
    actual = VERIFY(inspect, 'sha256:' + 'b' * 64 if mismatch == 'config' else CONFIG)
    assert actual == (identity if mismatch == 'none' else None)
