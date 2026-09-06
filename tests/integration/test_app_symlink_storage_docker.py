"""真实 Docker 共享卷验证 App 文件树的链接对象与产物身份。"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest

from builder.docker import DockerRunner
from builder.paths import BUILD_ROOT, PROJECT_ROOT


pytestmark = pytest.mark.skipif(
    os.environ.get("FLANGE_RUN_DOCKER_TESTS") != "1",
    reason="需要构建镜像，设置 FLANGE_RUN_DOCKER_TESTS=1 验证 App 共享卷符号链接",
)


def test_shared_source_links_survive_copy_and_manifest():
    program = """
import json
import os
from pathlib import Path
import stat
import sys

from builder.artifacts import ArtifactManifest, ArtifactSpec
from builder.digest import hash_path, tree_records
from builder.file_tree import copy_tree

root = Path(sys.argv[1])
source = root / 'source'
destination = root / 'install'
links = {
    'usr/lib/libsample.so': './libsample.so.1',
    'usr/lib/libsample.so.1': 'libsample.so.0',
    'usr/lib/optional.so': './future//liboptional.so',
    'usr/lib/optional-directory': './future//directory/',
}
# 共享驱动可能忽略 follow_symlinks=False；悬空链接属性由宿主验证。
visible_attributes = os.listxattr(source / 'usr/lib/libsample.so', follow_symlinks=False)
before = tree_records(source)
source_manifest = ArtifactManifest.capture(
    'app:copy-probe', 'source-input', [ArtifactSpec('install', source, 'tree')]
)
copy_tree(source, destination)
assert tree_records(source) == before
assert tree_records(destination) == before
assert hash_path(destination) == hash_path(source)
for name, target in links.items():
    assert os.readlink(destination / name) == target
assert (destination / 'usr/lib/libsample.so').read_bytes() == b'shared-library-fixture'
assert not (destination / 'usr/lib/optional.so').exists()
assert not (destination / 'usr/lib/optional-directory').exists()
assert stat.S_IMODE((destination / 'usr/lib/libsample.so.0').stat().st_mode) == 0o640
assert stat.S_IMODE((destination / 'usr/bin/tool').stat().st_mode) == 0o751
assert stat.S_IMODE(destination.stat().st_mode) == 0o751
assert stat.S_IMODE((destination / 'empty').stat().st_mode) == 0o750
assert not list((destination / 'empty').iterdir())
manifest = ArtifactManifest.capture(
    'app:copy-probe', 'source-input', [ArtifactSpec('install', destination, 'tree')]
)
assert manifest.identity == source_manifest.identity
manifest.write(root / 'manifest.json')
loaded = ArtifactManifest.load(root / 'manifest.json')
assert loaded is not None and loaded.validate()
assert loaded.identity == source_manifest.identity
print(json.dumps({'tree_matches': True, 'manifest_matches': True,
                  'links': len(links), 'container_link_attributes': visible_attributes}))
"""
    parent = BUILD_ROOT / "work"
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="app-symlink-storage-test-", dir=parent) as directory:
        root = Path(directory)
        source = root / "source"
        library = source / "usr/lib"
        library.mkdir(parents=True)
        targets = {
            "libsample.so": "./libsample.so.1",
            "libsample.so.1": "libsample.so.0",
            "optional.so": "./future//liboptional.so",
            "optional-directory": "./future//directory/",
        }
        attribute = "user.flange-copy-test" if sys.platform == "darwin" else ""
        attributes = {}
        for name, target in targets.items():
            link = library / name
            link.symlink_to(target)
            if attribute:
                # Linux 创建的链接模式固定为 0777，统一夹具以比较完整产物摘要。
                os.chmod(link, 0o777, follow_symlinks=False)
                # macOS 支持链接自身扩展属性；使用无害测试属性，同时保留平台已有属性。
                # Linux 通常不允许为链接设置 user 属性，仍验证共享目录内链接与清单语义。
                subprocess.run(
                    ["xattr", "-s", "-w", attribute, "copy-object", str(link)], check=True,
                )
                names = subprocess.run(
                    ["xattr", "-s", str(link)], text=True, capture_output=True, check=True,
                )
                attributes[name] = names.stdout.splitlines()
        # 先创建链接后创建目标，覆盖目录遍历期间目标尚未复制的真实场景。
        binary = library / "libsample.so.0"
        binary.write_bytes(b"shared-library-fixture")
        binary.chmod(0o640)
        executable = source / "usr/bin/tool"
        executable.parent.mkdir()
        executable.write_bytes(b"executable-fixture")
        executable.chmod(0o751)
        (source / "empty").mkdir(mode=0o750)
        source.chmod(0o751)
        result = DockerRunner(PROJECT_ROOT).run(
            ["python3", "-c", program, directory], capture=True,
        )
        if attribute:
            for name in targets:
                original = subprocess.run(
                    ["xattr", "-s", str(library / name)],
                    text=True, capture_output=True, check=True,
                )
                copied = subprocess.run(
                    ["xattr", "-s", str(root / "install/usr/lib" / name)],
                    text=True, capture_output=True, check=True,
                )
                assert attribute in original.stdout.splitlines()
                assert attribute not in copied.stdout.splitlines()
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["tree_matches"] and report["manifest_matches"]
    assert report["links"] == 4
    report["host_link_attributes"] = attributes
    print(json.dumps(report))
