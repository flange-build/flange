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


def _store(tmp_path: Path) -> SnapshotStore:
    return SnapshotStore(tmp_path / ".cache", "rootfs-base-", MagicMock())


def _make_snapshots(directory: Path, names: list[str]) -> list[Path]:
    """按给定顺序创建快照，mtime 递增（越靠后越新）。"""
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for index, name in enumerate(names):
        path = directory / f"rootfs-base-{name}.tar.gz"
        path.write_bytes(b"snapshot")
        os.utime(path, (1_700_000_000 + index, 1_700_000_000 + index))
        paths.append(path)
    return paths


def test_path_for拼出内容寻址的文件名(tmp_path):
    store = _store(tmp_path)
    assert store.path_for("abc123").name == "rootfs-base-abc123.tar.zst"


def test_resolve接受存量的gzip快照(tmp_path):
    """换压缩算法不该让已有快照全部作废、白付一次 Phase 1。"""
    store = _store(tmp_path)
    store.directory.mkdir(parents=True)
    legacy = store.directory / "rootfs-base-abc123.tar.gz"
    legacy.write_bytes(b"old")

    assert store.resolve("abc123") == legacy

    # 新格式存在时优先用新格式
    store.path_for("abc123").write_bytes(b"new")
    assert store.resolve("abc123") == store.path_for("abc123")


def test_resolve在都不存在时给出新格式路径(tmp_path):
    store = _store(tmp_path)
    assert store.resolve("abc123").suffix == ".zst"


def test_回收覆盖两种压缩格式(tmp_path, monkeypatch):
    monkeypatch.setenv(KEEP_ENV, "1")
    store = _store(tmp_path)
    paths = _make_snapshots(store.directory, ["old"])
    modern = store.path_for("new")
    modern.write_bytes(b"new")
    os.utime(modern, (1_700_001_000, 1_700_001_000))

    removed = store.prune()

    assert [item.name for item in removed] == ["rootfs-base-old.tar.gz"]
    assert modern.exists()


def test_保留最近使用的若干份(tmp_path, monkeypatch):
    monkeypatch.setenv(KEEP_ENV, "3")
    store = _store(tmp_path)
    paths = _make_snapshots(store.directory, ["a", "b", "c", "d", "e"])

    removed = store.prune()

    assert sorted(item.name for item in removed) == [
        "rootfs-base-a.tar.gz", "rootfs-base-b.tar.gz"]
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

    assert [item.name for item in removed] == ["rootfs-base-mid.tar.gz"]
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
    assert not (store.directory / "rootfs-base-a.tar.gz").exists()
    assert (store.directory / "rootfs-base-b.tar.gz").exists()


def test_环境变量非法时回退默认值(monkeypatch):
    monkeypatch.setenv(KEEP_ENV, "not-a-number")
    assert resolve_keep() == DEFAULT_KEEP

    monkeypatch.setenv(KEEP_ENV, "-3")
    assert resolve_keep() == 0

    monkeypatch.delenv(KEEP_ENV, raising=False)
    assert resolve_keep() == DEFAULT_KEEP
