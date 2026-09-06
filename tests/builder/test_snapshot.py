"""base 快照存取与容量治理。

快照单份 0.15–1.2GB，历史上无回收机制，实测在 120GB 构建卷上积累到 21 份共
12GB。这里锁定回收策略的三条性质：保留最近使用的 N 份、永不回收本次正在用的
那一份、可通过环境变量关闭。
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

from builder.snapshot import DEFAULT_KEEP, KEEP_ENV, SnapshotStore, resolve_keep
from builder.artifacts import ArtifactManifest, ArtifactSpec
import pytest


def _publish_manifest(path):
    manifest = ArtifactManifest.capture(
        "rootfs:base-snapshot", path.name, [ArtifactSpec("archive", path, allow_empty=False)]
    )
    manifest.write(SnapshotStore._manifest_path(path))


def _store(tmp_path: Path) -> SnapshotStore:
    return SnapshotStore(tmp_path / ".cache", "rootfs-base-", MagicMock())


def _make_snapshots(directory: Path, names: list[str]) -> list[Path]:
    """按给定顺序创建快照，mtime 递增（越靠后越新）。"""
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for index, name in enumerate(names):
        path = directory / f"rootfs-base-{name}.tar.zst"
        path.write_bytes(b"snapshot")
        _publish_manifest(path)
        os.utime(path, (1_700_000_000 + index, 1_700_000_000 + index))
        paths.append(path)
    return paths


def test_path_for拼出内容寻址的文件名(tmp_path):
    store = _store(tmp_path)
    assert store.path_for("abc123").name == "rootfs-base-abc123.tar.zst"


def test_resolve拒绝无清单的旧gzip快照(tmp_path):
    """旧快照不能作为新契约的成功证明。"""
    store = _store(tmp_path)
    store.directory.mkdir(parents=True)
    legacy = store.directory / "rootfs-base-abc123.tar.gz"
    legacy.write_bytes(b"old")

    assert store.resolve("abc123") != legacy
    assert not store.restore(legacy, tmp_path / "dest")

    # 新格式存在时优先用新格式
    store.path_for("abc123").write_bytes(b"new")
    assert store.resolve("abc123") == store.path_for("abc123")


def test_resolve在都不存在时给出新格式路径(tmp_path):
    store = _store(tmp_path)
    assert store.resolve("abc123").suffix == ".zst"


def test_回收当前格式且保留最新快照(tmp_path, monkeypatch):
    monkeypatch.setenv(KEEP_ENV, "1")
    store = _store(tmp_path)
    _make_snapshots(store.directory, ["old"])
    modern = store.path_for("new")
    modern.write_bytes(b"new")
    os.utime(modern, (1_700_001_000, 1_700_001_000))

    removed = store.prune()

    assert [item.name for item in removed] == ["rootfs-base-old.tar.zst"]
    assert modern.exists()


def test_保留最近使用的若干份(tmp_path, monkeypatch):
    monkeypatch.setenv(KEEP_ENV, "3")
    store = _store(tmp_path)
    paths = _make_snapshots(store.directory, ["a", "b", "c", "d", "e"])

    removed = store.prune()

    assert sorted(item.name for item in removed) == [
        "rootfs-base-a.tar.zst",
        "rootfs-base-b.tar.zst",
    ]
    assert not paths[0].exists() and not paths[1].exists()
    assert all(item.exists() for item in paths[2:])


def test_正在使用的快照不被回收(tmp_path, monkeypatch):
    """命中最老快照的构建不能把自己脚下的文件删掉。"""
    monkeypatch.setenv(KEEP_ENV, "2")
    store = _store(tmp_path)
    paths = _make_snapshots(store.directory, ["old", "mid", "new"])

    removed = store.prune(protect=paths[0])

    assert removed == []
    assert all(item.exists() for item in paths)


def test_keep为零时关闭回收(tmp_path, monkeypatch):
    monkeypatch.setenv(KEEP_ENV, "0")
    store = _store(tmp_path)
    paths = _make_snapshots(store.directory, ["a", "b", "c"])

    assert store.prune() == []
    assert all(item.exists() for item in paths)


def test_只回收同前缀的快照(tmp_path, monkeypatch):
    """rootfs 与 recovery 快照同目录共存，靠前缀区分，互不影响。"""
    monkeypatch.setenv(KEEP_ENV, "1")
    store = _store(tmp_path)
    _make_snapshots(store.directory, ["a", "b"])
    recovery = store.directory / "recovery-base-x.tar.gz"
    recovery.write_bytes(b"recovery")

    store.prune()

    assert recovery.exists()


def test_目录不存在时安全返回(tmp_path):
    assert _store(tmp_path).prune() == []


def test_命中时刷新mtime作为LRU依据(tmp_path, monkeypatch):
    monkeypatch.setenv(KEEP_ENV, "2")
    store = _store(tmp_path)
    paths = _make_snapshots(store.directory, ["old", "mid", "new"])

    # 复用最老的那份：刷新后它应当成为最新，回收时被保留
    store.restore(paths[0], tmp_path / "dest")
    removed = store.prune()

    assert [item.name for item in removed] == ["rootfs-base-mid.tar.zst"]
    assert paths[0].exists() and paths[2].exists()


def test_save打包并回收超额快照(tmp_path, monkeypatch):
    monkeypatch.setenv(KEEP_ENV, "2")
    store = _store(tmp_path)
    _make_snapshots(store.directory, ["a", "b"])
    target = store.path_for("new")
    # docker 是 mock，tar 不会真的生成文件；手动补上以模拟打包结果
    source = tmp_path / "rootfs"
    source.mkdir()

    def _fake_tar(command, **kwargs):
        if command[0] == "tar" and "-cf" in command:
            Path(command[command.index("-cf") + 1]).write_bytes(b"new")
        return MagicMock()

    store.docker.run_privileged.side_effect = _fake_tar
    store.save(source, target)

    assert target.exists()
    assert not (store.directory / "rootfs-base-a.tar.zst").exists()
    assert (store.directory / "rootfs-base-b.tar.zst").exists()


def test_环境变量非法时回退默认值(monkeypatch):
    monkeypatch.setenv(KEEP_ENV, "not-a-number")
    assert resolve_keep() == DEFAULT_KEEP

    monkeypatch.setenv(KEEP_ENV, "-3")
    assert resolve_keep() == 0

    monkeypatch.delenv(KEEP_ENV, raising=False)
    assert resolve_keep() == DEFAULT_KEEP


def test_tampered_archive_never_reaches_extractor(tmp_path):
    store = _store(tmp_path)
    archive = _make_snapshots(store.directory, ["a"])[0]
    archive.write_bytes(b"tampered")
    assert store.restore(archive, tmp_path / "dest") is False
    store.docker.run_privileged.assert_not_called()


def test_corrupt_manifest_never_reaches_extractor(tmp_path):
    store = _store(tmp_path)
    archive = _make_snapshots(store.directory, ["a"])[0]
    store._manifest_path(archive).write_text("broken json")
    assert store.restore(archive, tmp_path / "dest") is False
    store.docker.run_privileged.assert_not_called()


def test_extraction_failure_removes_partial_tree_and_quarantines_archive(tmp_path):
    store = _store(tmp_path)
    archive = _make_snapshots(store.directory, ["a"])[0]
    destination = tmp_path / "dest"
    destination.mkdir()
    (destination / "partial").write_bytes(b"partial")
    store.docker.run_privileged.side_effect = [None, RuntimeError("tar failed")]
    assert store.restore(archive, destination) is False
    assert list(destination.iterdir()) == []
    assert not archive.exists()
    assert archive.with_name(archive.name + ".corrupt").exists()
    assert not store._manifest_path(archive).exists()


def test_快照元数据配方变化使旧base缓存失效(tmp_path):
    from builder.rootfs_base import base_plan
    from tests.builder.context import component_context

    recipe = tmp_path / "builder/snapshot.py"
    recipe.parent.mkdir()
    recipe.write_text("# 旧归档语义\n")
    config = {
        "board": "test-board", "product": "default", "variant": "debug",
        "architecture": {"userspace": "aarch64"},
        "rootfs": {"url": "https://example.com/rootfs.tar.gz", "sha256": "a" * 64},
    }
    context = component_context(tmp_path, config)
    before = base_plan(config, "rootfs", context).fingerprint()
    recipe.write_text("# 保留扩展属性及 ACL\n")
    assert base_plan(config, "rootfs", context).fingerprint() != before


@pytest.mark.parametrize("error", [RuntimeError("tar failed"), KeyboardInterrupt()])
def test_interrupted_save_does_not_publish_temporary_archive(tmp_path, error):
    store = _store(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    target = store.path_for("new")

    def fail(command, **kwargs):
        if "-cf" in command:
            Path(command[command.index("-cf") + 1]).write_bytes(b"partial")
        raise error

    store.docker.run_privileged.side_effect = fail
    with pytest.raises(type(error)):
        store.save(source, target)
    assert not target.exists()
    assert not store._manifest_path(target).exists()
    assert not list(store.directory.glob("*.tmp"))
