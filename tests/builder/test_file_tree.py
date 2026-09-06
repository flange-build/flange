"""文件树复制的对象边界、权限与共享配方缓存回归。"""

import hashlib
import os
from pathlib import Path
import stat
from unittest.mock import MagicMock

import pytest

from builder import digest
from builder.file_tree import copy_tree
from builder.package_build import PackageBuilder
from tests.builder.app_support import app, builder


@pytest.mark.parametrize("target", ["./next", "dir//next", "./directory/", "/missing/absolute"])
def test_链接目标逐字保留而不被路径规范化(tmp_path, target):
    source = tmp_path / "source"
    source.mkdir()
    (source / "link").symlink_to(target)
    destination = tmp_path / "destination"
    copy_tree(source, destination)
    assert os.readlink(destination / "link") == target


def test_只读目录后序保留模式并保留空目录与排除规则(tmp_path):
    source = tmp_path / "source"
    locked = source / "locked"
    locked.mkdir(parents=True)
    binary = locked / "tool"
    binary.write_bytes(b"executable fixture")
    binary.chmod(0o751)
    (source / "empty").mkdir(mode=0o750)
    (source / ".git").mkdir()
    (source / ".git/config").write_text("excluded")
    locked.chmod(0o555)
    destination = tmp_path / "destination"
    try:
        copy_tree(source, destination, ignore=lambda _, names: [n for n in names if n == ".git"])
        assert (destination / "locked/tool").read_bytes() == binary.read_bytes()
        assert stat.S_IMODE((destination / "locked/tool").stat().st_mode) == 0o751
        assert stat.S_IMODE((destination / "locked").stat().st_mode) == 0o555
        assert stat.S_IMODE((destination / "empty").stat().st_mode) == 0o750
        assert list((destination / "empty").iterdir()) == []
        assert not (destination / ".git").exists()
    finally:
        locked.chmod(0o755)
        if (destination / "locked").is_dir():
            (destination / "locked").chmod(0o755)


def test_普通文件覆盖旧链接但不写入链接目标(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "file").write_text("new")
    external = tmp_path / "external"
    external.write_text("unchanged")
    destination = tmp_path / "destination"
    destination.mkdir()
    (destination / "file").symlink_to(external)
    copy_tree(source, destination)
    assert not (destination / "file").is_symlink()
    assert (destination / "file").read_text() == "new"
    assert external.read_text() == "unchanged"


@pytest.mark.parametrize("collision", ["directory", "directory-link"])
def test_节点类型冲突不改变目标树几何或沿目录链接写入(tmp_path, collision):
    source = tmp_path / "source"
    source.mkdir()
    destination = tmp_path / "destination"
    destination.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    if collision == "directory":
        (source / "entry").write_text("file")
        (destination / "entry").mkdir()
        error = IsADirectoryError
    else:
        (source / "entry").mkdir()
        (source / "entry/file").write_text("file")
        (destination / "entry").symlink_to(external)
        error = FileExistsError
    with pytest.raises(error):
        copy_tree(source, destination)
    assert not list(external.iterdir())
    assert not (destination / "entry/entry").exists()


def test_Package源码快照保留原始链接且成功后可复用(tmp_path, monkeypatch):
    engine = builder(tmp_path)
    directory = tmp_path / "sdk"
    directory.mkdir()
    (directory / "optional").symlink_to("./future//library")
    package = {"name": "sdk", "actions": {"build": ["compile"]}, "components": []}
    runner = MagicMock()

    def compile_package(command, **options):
        source = Path(options["cwd"])
        assert source != directory
        assert os.readlink(source / "optional") == "./future//library"
        (Path(options["env"]["FLANGE_PACKAGE_OUTPUT_DIR"]) / "sdk.bin").write_bytes(b"sdk")

    runner.run.side_effect = compile_package
    package_builder = PackageBuilder(engine.context, runner)
    first = package_builder.build(directory, package)
    assert first.validate()
    assert package_builder.build(directory, package).identity == first.identity
    assert runner.run.call_count == 1
    _change_copy_recipe(monkeypatch)
    assert package_builder.build(directory, package).validate()
    assert runner.run.call_count == 2


def _change_copy_recipe(monkeypatch):
    original = digest.file_sha256

    def changed(path):
        value = original(path)
        if path.name == "file_tree.py":
            return hashlib.sha256((value + "changed").encode()).hexdigest()
        return value

    monkeypatch.setattr(digest, "file_sha256", changed)


def test_公共复制配方变化使App重新构建(tmp_path, monkeypatch):
    source = app(tmp_path / "hello")
    engine = builder(tmp_path, apps={"hello": source})
    assert not engine.build_one("hello").root().reused
    assert engine.build_one("hello").root().reused
    _change_copy_recipe(monkeypatch)
    rebuilt = engine.build_one("hello")
    assert not rebuilt.root().reused
    assert rebuilt.validate()
