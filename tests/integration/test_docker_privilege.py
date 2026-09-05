"""通过真实 Compose 服务检查容器权限及镜像制作所需的挂载能力。"""

import json
import os

import pytest

from builder.docker import DockerRunner
from builder.paths import PROJECT_ROOT

pytestmark = pytest.mark.skipif(
    os.environ.get("FLANGE_RUN_DOCKER_TESTS") != "1",
    reason="需要预先准备 Docker 镜像，设置 FLANGE_RUN_DOCKER_TESTS=1 运行容器权限验收",
)


@pytest.mark.parametrize("privileged", [False, True])
def test_真实容器按请求提供挂载权限且不继承宿主开关(monkeypatch, privileged):
    # 设成与请求相反的值，确保容器使用本次意图而不是宿主残留环境。
    monkeypatch.setenv("FLANGE_BUILD_PRIVILEGED", "false" if privileged else "true")
    program = """
import json
from pathlib import Path
import subprocess
import tempfile

status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines())
admin = bool(int(status['CapEff'].strip(), 16) & (1 << 21))
with tempfile.TemporaryDirectory(prefix='flange-mount-') as directory:
    mount = subprocess.run(['mount', '-t', 'tmpfs', 'tmpfs', directory], capture_output=True)
    mounted = mount.returncode == 0
    try:
        if mounted:
            Path(directory, 'probe').write_text('flange')
    finally:
        if mounted:
            subprocess.run(['umount', directory], check=True)
print(json.dumps({'sys_admin': admin, 'mounted': mounted}))
"""
    result = DockerRunner(PROJECT_ROOT).run(
        ["python3", "-c", program], privileged=privileged, capture=True,
    )
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report == {"sys_admin": privileged, "mounted": privileged}
