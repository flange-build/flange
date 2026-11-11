"""Amlogic rootfs 的默认挂载、定制 fstab 保留与产物收集。"""

from __future__ import annotations

import pytest

from builder.platforms.amlogic.rootfs import AmlogicRootfsBuilder


@pytest.fixture
def builder():
    return AmlogicRootfsBuilder(docker=None, source=None)


def test_install_fstab_writes_label_mounts(builder, tmp_path):
    """fstab 包含 LABEL=rootfs / LABEL=boot 两行，并创建 /boot 挂载点。"""
    rootfs = tmp_path / "rootfs"
    (rootfs / "etc").mkdir(parents=True)

    builder._install_fstab(rootfs, {})

    fstab = (rootfs / "etc" / "fstab").read_text()
    assert "LABEL=rootfs" in fstab
    assert "LABEL=boot" in fstab
    assert (rootfs / "boot").is_dir()


@pytest.mark.parametrize("overlay_text", [
    "LABEL=custom  /  ext4  defaults  0  1\n",
    "# 由启动脚本负责挂载\n",
    "",
])
def test_install_fstab_respects_existing_overlay(builder, tmp_path, overlay_text):
    """定制阶段的 fstab 即使为空或仅含注释，也不能被默认挂载覆盖。"""
    rootfs = tmp_path / "rootfs"
    (rootfs / "etc").mkdir(parents=True)
    (rootfs / "etc" / "fstab").write_text(overlay_text)

    builder._install_fstab(rootfs, {})

    assert (rootfs / "etc" / "fstab").read_text() == overlay_text


def test_collect_returns_rootfs_key(builder, tmp_path):
    """collect 返回 {'rootfs': <path>}。"""
    builder._output = tmp_path / "rootfs.img"
    out = builder.collect(None, {})
    assert out == {"rootfs": tmp_path / "rootfs.img"}
