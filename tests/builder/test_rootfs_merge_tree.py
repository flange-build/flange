"""overlay / 内核模块合并进 rootfs 时不得改动已有目录，属主一律 root。"""

import io
import os
import subprocess
import tarfile

from builder.rootfs import _merge_tree_command


def _source(tmp_path):
    """模拟 umask 002 下的仓库检出：目录 775、文件 664、可执行 775。"""
    src = tmp_path / "overlay"
    (src / "etc/flange").mkdir(parents=True)
    (src / "usr/local/sbin").mkdir(parents=True)
    (src / "etc/flange/a.conf").write_text("a\n")
    (src / "usr/local/sbin/tool").write_text("#!/bin/sh\n")
    (src / "etc/null.service").symlink_to("/dev/null")
    for path in [src, *src.rglob("*")]:
        if path.is_symlink():
            continue
        path.chmod(0o775 if path.is_dir() or path.name == "tool" else 0o664)
    return src


def _rootfs(tmp_path):
    """rootfs 已有 /etc（755）与 merged-usr 风格的目录符号链接 /usr/local -> opt。"""
    dest = tmp_path / "rootfs"
    (dest / "etc").mkdir(parents=True)
    for path in (dest, dest / "etc"):
        path.chmod(0o755)
    (dest / "usr/opt").mkdir(parents=True)
    (dest / "usr/local").symlink_to("opt")
    return dest


def _mode(path):
    return path.lstat().st_mode & 0o777


def test_existing_directories_keep_metadata(tmp_path):
    src, dest = _source(tmp_path), _rootfs(tmp_path)

    subprocess.run(_merge_tree_command(src, dest), check=True)

    # cp -a src/. dest 会把 dest 与 dest/etc 改成源目录的 775。
    assert _mode(dest) == 0o755
    assert _mode(dest / "etc") == 0o755
    # cp -a 在这里直接报错；tar 不能把链接替换成真实目录（merged-usr 的 /lib 就是这种链接）。
    assert (dest / "usr/local").is_symlink()
    assert (dest / "usr/opt/sbin/tool").read_text() == "#!/bin/sh\n"


def test_new_entries_drop_group_and_other_write(tmp_path):
    src, dest = _source(tmp_path), _rootfs(tmp_path)

    subprocess.run(_merge_tree_command(src, dest), check=True)

    assert _mode(dest / "etc/flange") == 0o755
    assert _mode(dest / "etc/flange/a.conf") == 0o644
    assert _mode(dest / "usr/opt/sbin/tool") == 0o755
    assert os.readlink(dest / "etc/null.service") == "/dev/null"


def test_archive_entries_are_owned_by_root(tmp_path):
    """解包端以 root 运行时按归档属主落盘；这里检查打包端给出的属主。"""
    src = _source(tmp_path)
    create = _merge_tree_command(src, tmp_path)[2].split("|")[0].split(";", 1)[1]

    archive = subprocess.run(
        ["bash", "-c", create, "bash", str(src)], check=True, capture_output=True,
    ).stdout

    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        members = tar.getmembers()
    assert members
    assert {(m.uid, m.gid) for m in members} == {(0, 0)}


def test_source_failure_fails_the_command(tmp_path):
    dest = _rootfs(tmp_path)

    result = subprocess.run(
        _merge_tree_command(tmp_path / "missing", dest), capture_output=True,
    )

    assert result.returncode != 0
