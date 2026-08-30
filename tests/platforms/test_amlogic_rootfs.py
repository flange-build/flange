"""AmlogicRootfsBuilder 单元测试 — 聚焦 LABEL 挂载与轻量行为。

不在此处覆盖完整 chroot/apt 流程（成本高且与基类共享），仅验证：
- 实例化与 component 名
- _install_fstab 写入 LABEL=rootfs / LABEL=boot 两行
- _install_fstab 尊重 overlay 已写入的 fstab（含真实挂载项时不覆盖）
- collect 返回 ``rootfs`` 键，路径为 _output
"""

from __future__ import annotations

from pathlib import Path

import pytest

from builder.platforms.amlogic.rootfs import AmlogicRootfsBuilder


@pytest.fixture
def builder():
    return AmlogicRootfsBuilder(docker=None, source=None)


def test_instantiate(builder):
    assert builder.component == "rootfs"


def test_install_fstab_writes_label_mounts(builder, tmp_path):
    """fstab 包含 LABEL=rootfs / LABEL=boot 两行，并创建 /boot 挂载点。"""
    rootfs = tmp_path / "rootfs"
    (rootfs / "etc").mkdir(parents=True)

    builder._install_fstab(rootfs, {})

    fstab = (rootfs / "etc" / "fstab").read_text()
    assert "LABEL=rootfs" in fstab
    assert "LABEL=boot" in fstab
    assert (rootfs / "boot").is_dir()


def test_install_fstab_respects_existing_overlay(builder, tmp_path):
    """已有 overlay 写入的 fstab（含 LABEL= 等真实挂载项）不被覆盖。"""
    rootfs = tmp_path / "rootfs"
    (rootfs / "etc").mkdir(parents=True)
    overlay_text = (
        "# overlay-provided fstab\n"
        "LABEL=custom  /  ext4  defaults  0  1\n"
    )
    (rootfs / "etc" / "fstab").write_text(overlay_text)

    builder._install_fstab(rootfs, {})

    assert (rootfs / "etc" / "fstab").read_text() == overlay_text


def test_install_fstab_overwrites_ubuntu_base_placeholder(builder, tmp_path):
    """ubuntu-base 自带占位 fstab（仅注释、无挂载项）会被覆盖。"""
    rootfs = tmp_path / "rootfs"
    (rootfs / "etc").mkdir(parents=True)
    (rootfs / "etc" / "fstab").write_text("# UNCONFIGURED FSTAB FOR BASE SYSTEM\n")

    builder._install_fstab(rootfs, {})

    fstab = (rootfs / "etc" / "fstab").read_text()
    assert "LABEL=rootfs" in fstab
    assert "LABEL=boot" in fstab


def test_collect_returns_rootfs_key(builder, tmp_path):
    """collect 返回 {'rootfs': <path>}。"""
    builder._output = tmp_path / "rootfs.img"
    out = builder.collect(None, {})
    assert out == {"rootfs": tmp_path / "rootfs.img"}


def test_get_base_cache_path_returns_none_without_cache(builder):
    """无 cache 注入时 _get_base_cache_path 返回 None（compile 走非缓存分支）。"""
    builder.cache = None
    assert builder._get_base_cache_path({"board": "x"}) is None
