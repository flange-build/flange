"""APT 的互斥边界覆盖真实共享目录，而不是调用者工作区。"""

import multiprocessing
import queue
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from builder.apt import AptCache
from builder.build_dependencies import UbuntuBuildDependencies
from builder.paths import PROJECT_ROOT
from builder.rootfs_base import build_base
from tests.builder.app_support import builder


def _install(tool, tag, events, release):
    class Runner:
        def run(self, command):
            events.put((tag, command[1]))
            if command[1] == "update" and not release.wait(10):
                raise TimeoutError("测试未释放 APT 事务")

    events.put((tag, "ready"))
    UbuntuBuildDependencies(Runner(), Path(tool)).install(["example:{arch}"], "aarch64")


def test_external_workspaces_lock_the_compose_cache(tmp_path):
    first, second = builder(tmp_path / "first"), builder(tmp_path / "second")
    from dataclasses import replace

    from builder.app_build import AppBuilder

    context = replace(second.context, tool_root=first.context.tool_root)
    second = AppBuilder(second._docker, second._source, second._config, context=context)
    assert first.context.build_root != second.context.build_root
    assert first.build_dependencies.cache == second.build_dependencies.cache
    compose = yaml.safe_load((PROJECT_ROOT / "docker-compose.yml").read_text())
    mounts = dict(
        entry.split(":")[:2] for entry in compose["services"]["build"]["volumes"]
    )
    cache = AptCache.for_tool(PROJECT_ROOT)
    for target, actual in (
        ("/cache/apt", cache.archives),
        ("/var/lib/apt/lists", cache.lists),
    ):
        source = next(
            source for source, destination in mounts.items() if destination == target
        )
        assert (PROJECT_ROOT / source).resolve() == actual


@pytest.mark.parametrize("shared", [True, False])
def test_apt_transactions_serialize_only_when_cache_is_shared(tmp_path, shared):
    ctx = multiprocessing.get_context("spawn")
    events = ctx.Queue()
    release_first, release_second = ctx.Event(), ctx.Event()
    release_second.set()
    first = ctx.Process(
        target=_install, args=(str(tmp_path / "tool"), "first", events, release_first)
    )
    other_tool = tmp_path / ("tool" if shared else "other-tool")
    second = ctx.Process(
        target=_install, args=(str(other_tool), "second", events, release_second)
    )
    first.start()
    try:
        assert events.get(timeout=5) == ("first", "ready")
        assert events.get(timeout=5) == ("first", "update")
        second.start()
        assert events.get(timeout=5) == ("second", "ready")
        if shared:
            with pytest.raises(queue.Empty):
                events.get(timeout=0.2)
            release_first.set()
            assert [events.get(timeout=5) for _ in range(3)] == [
                ("first", "install"),
                ("second", "update"),
                ("second", "install"),
            ]
        else:
            assert events.get(timeout=5) == ("second", "update")
            assert events.get(timeout=5) == ("second", "install")
            release_first.set()
            assert events.get(timeout=5) == ("first", "install")
    finally:
        release_first.set()
        for process in (first, second):
            if process.pid:
                process.join(timeout=10)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
        events.close()
    assert first.exitcode == second.exitcode == 0


def test_lock_order_alias_deduplication_and_partial_failure(tmp_path, monkeypatch):
    real = tmp_path / "a"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    events = []

    @contextmanager
    def lock(path):
        events.append(("enter", path.name))
        if path.name == ".z.flange.lock":
            raise OSError("第二个资源无法加锁")
        try:
            yield
        finally:
            events.append(("exit", path.name))

    monkeypatch.setattr("builder.apt.FileLock", lock)
    with AptCache(real, alias).locked():
        pass
    assert events == [("enter", ".a.flange.lock"), ("exit", ".a.flange.lock")]
    events.clear()
    with (
        pytest.raises(OSError, match="第二个"),
        AptCache(tmp_path / "z", alias).locked(),
    ):
        pytest.fail("不应进入事务")
    assert events == [
        ("enter", ".a.flange.lock"),
        ("enter", ".z.flange.lock"),
        ("exit", ".a.flange.lock"),
    ]


def test_failed_apt_releases_locks_and_does_not_mark_packages_installed(tmp_path):
    runner = MagicMock()
    runner.run.side_effect = RuntimeError("APT 失败")
    installer = UbuntuBuildDependencies(runner, tmp_path)
    with pytest.raises(RuntimeError, match="APT 失败"):
        installer.install(["example:{arch}"], "aarch64")
    assert not installer.index_updated and not installer.installed
    # 独立进程能继续进入相同缓存；同线程重入不能证明异常后已释放。
    ctx = multiprocessing.get_context("spawn")
    events, released = ctx.Queue(), ctx.Event()
    released.set()
    process = ctx.Process(
        target=_install, args=(str(tmp_path), "retry", events, released)
    )
    process.start()
    process.join(timeout=10)
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
        pytest.fail("APT 异常后仍占用缓存锁")
    assert process.exitcode == 0
    events.close()


def test_rootfs_mount_clean_and_unmount_are_inside_actual_cache_lock(
    tmp_path, monkeypatch
):
    context = builder(tmp_path).context
    events = []

    @contextmanager
    def locked(cache):
        assert cache.archives.parent == context.build_root / "cache/apt"
        assert cache.lists is None
        events.append("lock")
        yield
        events.append("unlock")

    @contextmanager
    def chroot(root, docker):
        instance = MagicMock()
        instance.bind_mount.side_effect = lambda source, target: events.append(
            (source, str(target))
        )
        instance.run.side_effect = lambda command, **kwargs: events.append(command)
        yield instance
        events.append("unmount")

    monkeypatch.setattr(AptCache, "locked", locked)
    monkeypatch.setattr("builder.rootfs_base.ChrootContext", chroot)
    values = {
        "distro": "ubuntu",
        "architecture": "aarch64",
        "tarball": {},
        "emulator": "qemu-aarch64-static",
        "apt": {"extra_sources": [], "packages": []},
    }
    plan, source = MagicMock(), MagicMock()
    plan.value.side_effect = values.__getitem__
    source.ensure_download.return_value = tmp_path / "base.tar.gz"
    root = tmp_path / "rootfs"
    build_base(
        plan,
        root,
        context=context,
        source=source,
        docker=MagicMock(),
        status=lambda value: None,
    )
    from builder.digest import digest_value
    identity = digest_value({"distro": "ubuntu", "architecture": "aarch64",
                             "tarball": {}, "sources": []})[:20]
    assert events == [
        "lock",
        (str(context.build_root / "cache/apt" / identity), str(root / "var/cache/apt/archives")),
        ["apt-get", "update"],
        ["apt-get", "clean"],
        "unmount",
        "unlock",
    ]


def test_options_and_locks_reference_same_directories(tmp_path):
    runner = MagicMock()
    installer = UbuntuBuildDependencies(runner, tmp_path)
    installer.install(["example:{arch}"], "aarch64")
    for call in runner.run.call_args_list:
        assert f"Dir::Cache::archives={installer.cache.archives}" in call.args[0]
        assert f"Dir::State::lists={installer.cache.lists}" in call.args[0]
    assert "example:arm64" in runner.run.call_args.args[0]
    for directory in (installer.cache.archives, installer.cache.lists):
        assert directory.with_name(f".{directory.name}.flange.lock").is_file()
