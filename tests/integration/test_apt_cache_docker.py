"""两个 Docker 工作区使用共享 APT 缓存，真实执行 update/install/clean。"""

import os
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from builder.docker import DockerRunner
from builder.paths import PROJECT_ROOT

pytestmark = pytest.mark.skipif(
    os.environ.get("FLANGE_RUN_DOCKER_TESTS") != "1",
    reason="需要 Docker 镜像，设置 FLANGE_RUN_DOCKER_TESTS=1 运行共享卷锁验收",
)

WORKER = """
import subprocess
import sys
import time
from pathlib import Path
from builder.build_dependencies import UbuntuBuildDependencies

root, tag = Path(sys.argv[1]), sys.argv[2]
empty = root / 'empty.sources'
safe_sources = ['-o', 'Dir::Etc::sourcelist=' + str(empty),
                '-o', 'Dir::Etc::sourceparts=-']

class Runner:
    def run(self, command):
        if command[1] == 'update':
            # 目录创建若重叠则立即失败，证明 update 到 install 是同一事务。
            (root / 'critical').mkdir()
            (root / ('entered-' + tag)).write_text('ready')
            if tag == 'first':
                deadline = time.monotonic() + 30
                while not (root / 'release-first').exists():
                    if time.monotonic() > deadline:
                        raise TimeoutError('未收到事务释放信号')
                    time.sleep(0.05)
        result = subprocess.run(command + safe_sources, capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        if command[1] == 'install':
            (root / 'critical').rmdir()
        return result

installer = UbuntuBuildDependencies(Runner(), root / 'tool')
(root / ('started-' + tag)).write_text('ready')
# base-files 已在构建镜像中安装；使用空源和独立缓存，不访问网络及生产缓存。
installer.install(['base-files'], 'aarch64')
cache = installer.cache
with cache.locked():
    lock = cache.archives.with_name('.' + cache.archives.name + '.flange.lock')
    inode = lock.stat().st_ino
    (cache.archives / 'obsolete.deb').write_text('缓存清理夹具')
    subprocess.run(['apt-get', 'clean', *cache.options], check=True, timeout=30)
    assert lock.stat().st_ino == inode
    assert not (cache.archives / 'obsolete.deb').exists()
(root / ('done-' + tag)).write_text('passed')
"""


def _wait_for(path, future):
    deadline = time.monotonic() + 30
    while not path.exists():
        if future.done():
            future.result()
            pytest.fail(f"容器结束但缺少同步信号：{path.name}")
        if time.monotonic() >= deadline:
            pytest.fail(f"等待容器同步信号超时：{path.name}")
        time.sleep(0.05)


def test_two_container_workspaces_share_apt_lock_and_keep_it_after_clean(tmp_path):
    worker = tmp_path / "worker.py"
    worker.write_text(WORKER)
    (tmp_path / "empty.sources").write_text("")
    for tag in ("first", "second"):
        (tmp_path / tag).mkdir()

    def start(tag):
        return DockerRunner(PROJECT_ROOT).run(
            ["python3", str(worker), str(tmp_path), tag],
            cwd=str(tmp_path / tag),
            capture=True,
            extra_mounts=[tmp_path],
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(start, "first")
        try:
            _wait_for(tmp_path / "entered-first", first)
            second = pool.submit(start, "second")
            _wait_for(tmp_path / "started-second", second)
            time.sleep(0.3)
            assert not (tmp_path / "entered-second").exists()
        finally:
            (tmp_path / "release-first").write_text("release")
        assert first.result(timeout=40).returncode == 0
        assert second.result(timeout=40).returncode == 0
    assert (tmp_path / "done-first").is_file()
    assert (tmp_path / "done-second").is_file()
    assert not (tmp_path / "critical").exists()
