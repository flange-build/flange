"""验证可变 rootfs 与持久化产物隔离，以及失败后的安全清理。"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from builder.docker import BuildError
from builder.rootfs_storage import _active_mounts, rootfs_staging
from builder.rootfs_base import base_plan
from tests.builder.context import component_context
from tests.builder.test_rootfs_cache import _builder, _config


@pytest.mark.parametrize("component", ["rootfs", "recovery"])
def test_staging_uses_native_directory_and_ignores_tmpdir(tmp_path, monkeypatch, component):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    with rootfs_staging(component) as rootfs:
        assert rootfs.parent.parent == Path("/var/tmp")
        assert rootfs.name == component
        (rootfs / "file").write_text("content")
    assert not rootfs.parent.exists()


@pytest.mark.parametrize("failure", [BuildError("APT failed"), KeyboardInterrupt()])
def test_failure_removes_unmounted_staging(failure):
    with pytest.raises(type(failure)) as caught:
        with rootfs_staging("rootfs") as rootfs:
            raise failure
    assert caught.value is failure
    assert not rootfs.parent.exists()


def test_each_staging_scope_is_independent():
    with rootfs_staging("rootfs") as first, rootfs_staging("rootfs") as second:
        assert first != second
        (first / "state").write_text("first")
        assert not (second / "state").exists()


@pytest.mark.parametrize("failed", [False, True])
def test_remaining_mount_refuses_recursive_removal(tmp_path, monkeypatch, failed):
    directory = tmp_path / "temporary"
    directory.mkdir()
    monkeypatch.setattr("builder.rootfs_storage.tempfile.mkdtemp", lambda **kwargs: str(directory))
    monkeypatch.setattr("builder.rootfs_storage._active_mounts", lambda _: [directory / "rootfs/dev"])
    cleanup = MagicMock()
    monkeypatch.setattr("builder.rootfs_storage.shutil.rmtree", cleanup)
    failure = BuildError("APT failed")
    with pytest.raises(BuildError) as caught:
        with rootfs_staging("rootfs"):
            if failed:
                raise failure
    cleanup.assert_not_called()
    assert directory.exists()
    if failed:
        assert caught.value is failure
        assert "仍有挂载" in failure.__notes__[0]
    else:
        assert "仍有挂载" in str(caught.value)


def test_mountinfo_matches_tree_boundary_and_decodes_paths(tmp_path, monkeypatch):
    root = (tmp_path / "root fs").resolve()
    escaped = str(root).replace(" ", r"\040")
    records = [
        f"100 1 0:1 / {escaped}/dev rw - tmpfs tmpfs rw",
        f"101 1 0:1 / {escaped}-other/dev rw - tmpfs tmpfs rw",
        "102 1 0:1 / /dev rw - tmpfs tmpfs rw",
    ]
    monkeypatch.setattr("builder.rootfs_storage.sys.platform", "linux")
    monkeypatch.setattr(Path, "read_text", lambda self: "\n".join(records))
    assert _active_mounts(root) == [root / "dev"]


@pytest.mark.parametrize("hit", [False, True])
def test_entire_rootfs_lifecycle_uses_native_tree_and_publishes_outside_it(tmp_path, hit):
    builder = _builder(tmp_path)
    trees = []

    def record(rootfs, *args):
        assert rootfs.exists()
        assert builder.context.build_root not in rootfs.parents
        trees.append(rootfs)

    def restore(rootfs_cache, rootfs):
        record(rootfs)
        return hit

    def make_image(rootfs, config):
        record(rootfs)
        builder._output = builder._work_dir / "rootfs.img"
        builder._output.write_bytes(b"image")

    builder._extract_base = restore
    for name in ("_build_phase1", "_save_base_snapshot", "_build_phase2", "_post_customize",
                 "_install_fstab", "_ensure_api_mountpoints"):
        setattr(builder, name, record)
    builder._build_image = make_image
    outputs = builder.build(_config())
    assert len(set(trees)) == 1
    assert not trees[0].exists()
    assert outputs["rootfs"].read_bytes() == b"image"
    assert builder.context.build_root in outputs["rootfs"].parents


def test_storage_recipe_changes_base_snapshot_identity(tmp_path):
    recipe = tmp_path / "builder/rootfs_storage.py"
    recipe.parent.mkdir()
    recipe.write_text("# 原生存储 v1\n")
    context = component_context(tmp_path, _config())
    before = base_plan(_config(), "rootfs", context).fingerprint()
    recipe.write_text("# 原生存储 v2\n")
    assert base_plan(_config(), "rootfs", context).fingerprint() != before
