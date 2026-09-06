"""真实 Docker 验证原生活树、快照往返和 ext4 镜像内的 Linux 元数据。"""

import json
import os
import tempfile

import pytest

from builder.docker import DockerRunner
from builder.paths import BUILD_ROOT, PROJECT_ROOT


pytestmark = pytest.mark.skipif(
    os.environ.get("FLANGE_RUN_DOCKER_TESTS") != "1",
    reason="需要构建镜像，设置 FLANGE_RUN_DOCKER_TESTS=1 验证 rootfs 存储与成像",
)


def test_native_permissions_survive_snapshot_and_image():
    program = """
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

from builder.docker import DockerRunner
from builder.rootfs_storage import rootfs_staging
from builder.snapshot import SnapshotStore

output = Path(sys.argv[1])
docker = DockerRunner()
store = SnapshotStore(output, 'base-', docker)
archive = store.path_for('storage-probe')
# 由 setcap cap_net_raw=ep 与 setfacl -m u:3456:r-x 实测生成。
# ACL 依次描述所有者 rwx、UID 3456 r-x、所属组 r-x、mask r-x、其他用户无权限。
attributes = {
    'security.capability': bytes.fromhex('0100000200200000000000000000000000000000'),
    'system.posix_acl_access': bytes.fromhex(
        '0200000001000700ffffffff02000500800d000004000500ffffffff10000500ffffffff20000000ffffffff'
    ),
    'user.flange': b'metadata-probe',
}

def acl_entries(value):
    assert struct.unpack_from('<I', value)[0] == 2
    entries = struct.iter_unpack('<HHI', value[4:])
    # 只有具名用户/组条目的 ID 有意义；debugfs 对其余 ID 填 0，内核填 0xffffffff。
    return [(tag, permissions, identity if tag in (2, 8) else None)
            for tag, permissions, identity in entries]

with rootfs_staging('rootfs') as tree:
    locked = tree / 'etc/sudoers.d'
    locked.mkdir(parents=True, mode=0o550)
    (locked / 'README.dpkg-new').write_text('root can unpack here')
    owned = tree / 'owned'
    owned.write_text('target ownership')
    os.chown(owned, 1000, 1000)
    owned.chmod(0o440)
    privileged = tree / 'privileged'
    shutil.copy2('/usr/bin/true', privileged)
    os.chown(privileged, 1234, 2345)
    privileged.chmod(0o750)
    for name, value in attributes.items():
        os.setxattr(privileged, name, value)
    os.link(privileged, tree / 'hardlink')
    (tree / 'symlink').symlink_to('privileged')
    store.save(tree, archive)
assert not tree.exists()
with rootfs_staging('rootfs') as restored:
    assert store.restore(archive, restored)
    metadata = (restored / 'owned').stat()
    assert (metadata.st_uid, metadata.st_gid, metadata.st_mode & 0o7777) == (1000, 1000, 0o440)
    assert (restored / 'etc/sudoers.d').stat().st_mode & 0o7777 == 0o550
    privileged = restored / 'privileged'
    metadata = privileged.stat()
    assert (metadata.st_uid, metadata.st_gid, metadata.st_mode & 0o7777) == (1234, 2345, 0o750)
    for name, value in attributes.items():
        assert os.getxattr(privileged, name) == value, name
    assert privileged.stat().st_ino == (restored / 'hardlink').stat().st_ino
    assert os.readlink(restored / 'symlink') == 'privileged'
    image = output / 'rootfs.img'
    subprocess.run(['truncate', '-s', '32M', str(image)], check=True)
    subprocess.run(['mke2fs', '-t', 'ext4', '-F', '-q', '-d', str(restored), str(image)], check=True)
assert not restored.exists()
result = subprocess.run(['debugfs', '-R', 'stat /owned', str(image)], text=True, capture_output=True, check=True)
assert re.search(r'User:\\s*1000\\s+Group:\\s*1000', result.stdout), result.stdout
assert re.search(r'Mode:\\s*0440', result.stdout), result.stdout
for name, value in attributes.items():
    extracted = output / (name + '.bin')
    command = 'ea_get -f ' + json.dumps(str(extracted)) + ' /privileged ' + name
    subprocess.run(['debugfs', '-R', command, str(image)], check=True, capture_output=True)
    actual = extracted.read_bytes()
    if name == 'system.posix_acl_access':
        assert acl_entries(actual) == acl_entries(value), name
    else:
        assert actual == value, name
subprocess.run(['e2fsck', '-f', '-n', str(image)], check=True, capture_output=True)
print(json.dumps({'native_write': True, 'snapshot_metadata': True, 'image_metadata': True,
                  'extended_metadata': True, 'cleaned': True}))
"""
    parent = BUILD_ROOT / "work"
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rootfs-storage-test-", dir=parent) as output:
        result = DockerRunner(PROJECT_ROOT).run(
            ["python3", "-c", program, output], privileged=True, capture=True,
            env={"TMPDIR": output},
        )
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report == {
        "native_write": True, "snapshot_metadata": True, "image_metadata": True, "cleaned": True,
        "extended_metadata": True,
    }
