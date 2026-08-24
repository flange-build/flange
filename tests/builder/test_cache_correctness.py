"""缓存正确性回归：源码身份、输入矩阵与动态产物门禁。"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from builder.cache import BuildCache
from builder.docker import BuildError
from builder.engine import BuildEngine
from builder.source import SourceManager


def _config() -> dict:
    return {
        "board": "cache-test",
        "product": "default",
        "variant": "release",
        "arch": "aarch64",
        "platform": "rockchip",
        "soc": "rk3568",
        "kernel": {"dts": "cache-test"},
        "kernel_device": {"board_dts_path": "board-a.dts"},
        "bootloader": {},
        "rkbin": {"ini_prefix": "RK3568"},
        "boot": {},
        "rootfs": {
            "url": "https://example.com/ubuntu-base.tar.gz",
            "sha256": "a" * 64,
            "packages": [],
            "custom_packages": [],
            "hostname": "flange",
        },
        "storage": {"type": "emmc", "size": "8G"},
        "partitions": {"format": "gpt", "entries": []},
        "recovery": {"enabled": False},
        "amp": {"enabled": False},
        "image": {},
    }


def _cache(project: Path, config: dict | None = None) -> BuildCache:
    return BuildCache(
        config or _config(),
        target_base=project / "target",
        project_root=project,
    )


def _kernel_artifacts(cache: BuildCache) -> None:
    output = cache.target_dir / "kernel"
    output.mkdir(parents=True, exist_ok=True)
    (output / "Image").write_bytes(b"kernel")
    (output / "cache-test.dtb").write_bytes(b"dtb")


def test_branch_head未变化时允许命中(tmp_path: Path, monkeypatch):
    config = _config()
    config["repos"] = {
        "kernel": {"repo": "https://example.com/kernel.git", "branch": "main"}
    }
    config["kernel"]["from_repo"] = "kernel"
    (tmp_path / ".build/sources/repos/kernel").mkdir(parents=True)
    cache = _cache(tmp_path, config)
    monkeypatch.setattr(cache, "_git_head", lambda _path: "stable-head")
    _kernel_artifacts(cache)

    cache.store("kernel")

    assert cache.is_up_to_date("kernel")


def test_store重新计算构建后head(tmp_path: Path, monkeypatch):
    config = _config()
    config["kernel"]["repo"] = "https://example.com/kernel.git"
    repo = tmp_path / ".build/sources/kernel/cache-test"
    repo.mkdir(parents=True)
    state = {"head": "before"}
    cache = _cache(tmp_path, config)
    monkeypatch.setattr(cache, "_git_head", lambda _path: state["head"])
    cache.compute_hash("kernel")

    state["head"] = "after"
    cache.store("kernel")
    fresh = _cache(tmp_path, config)
    monkeypatch.setattr(fresh, "_git_head", lambda _path: state["head"])

    hash_file = cache.target_dir / "kernel/.build_hash"
    assert hash_file.read_text() == fresh.compute_hash("kernel")


def test_同一组件预同步与构建只fetch一次(tmp_path: Path, monkeypatch):
    manager = SourceManager(
        tmp_path / ".build/sources", project_root=tmp_path)
    repo = manager.sources_dir / "kernel/cache-test"
    repo.mkdir(parents=True)
    calls = []
    monkeypatch.setattr(
        manager, "_fetch_reset_branch",
        lambda path, branch: calls.append((path, branch)),
    )
    config = _config()
    config["kernel"].update({
        "repo": "https://example.com/kernel.git", "branch": "main"})

    manager.prepare_cache_inputs("kernel", config)
    manager.ensure("kernel", config)

    assert calls == [(repo, "main")]


def test_external_git_app已存在时仍同步branch(tmp_path: Path, monkeypatch):
    manager = SourceManager(
        tmp_path / ".build/sources", project_root=tmp_path)
    app_dir = manager.sources_dir / "apps/demo"
    app_dir.mkdir(parents=True)
    calls = []
    monkeypatch.setattr(
        manager, "_fetch_reset_branch",
        lambda path, branch: calls.append((path, branch)),
    )
    config = {
        "external_apps": {
            "demo": {"git": "https://example.com/demo.git", "branch": "main"}
        }
    }

    assert manager.ensure_app("demo", config) == app_dir
    assert calls == [(app_dir, "main")]


def test_engine先准备源码再查询缓存(tmp_path: Path, monkeypatch):
    engine = BuildEngine(_config(), project_dir=tmp_path)
    calls = []
    monkeypatch.setattr(
        engine.source, "prepare_cache_inputs",
        lambda component, config: calls.append(("prepare", component)),
    )
    monkeypatch.setattr(
        engine.cache, "is_up_to_date",
        lambda component: calls.append(("cache", component)) or True,
    )

    engine._build_components("app")

    assert calls == [("prepare", "app"), ("cache", "app")]


def test_仓库内vendor_app可命中而仓库外local_path强制重建(tmp_path: Path):
    project = tmp_path / "project"
    inside = project / "components/vendor/demo"
    outside = tmp_path / "outside/demo"
    for source in (inside, outside):
        source.mkdir(parents=True)
        (source / "app.yaml").write_text("name: demo")

    inside_config = _config()
    inside_config["rootfs"]["custom_packages"] = ["demo"]
    inside_config["external_apps"] = {"demo": {"local_path": str(inside)}}
    inside_cache = _cache(project, inside_config)
    deb = inside_cache.target_dir / "app/demo.deb"
    deb.parent.mkdir(parents=True)
    deb.write_bytes(b"deb")
    inside_cache.store("app")
    assert inside_cache.is_up_to_date("app")

    outside_config = copy.deepcopy(inside_config)
    outside_config["external_apps"]["demo"]["local_path"] = str(outside)
    outside_cache = _cache(project, outside_config)
    outside_cache.store("app")

    assert not outside_cache.is_up_to_date("app")


def test_so载荷变化使app哈希失效(tmp_path: Path):
    app = tmp_path / "components/app/demo"
    app.mkdir(parents=True)
    (app / "app.yaml").write_text("name: demo")
    library = app / "libdemo.so"
    library.write_bytes(b"v1")
    config = _config()
    config["rootfs"]["custom_packages"] = ["demo"]
    before = _cache(tmp_path, config).compute_hash("app")

    library.write_bytes(b"v2")

    assert before != _cache(tmp_path, config).compute_hash("app")


@pytest.mark.parametrize(
    ("component", "path", "value"),
    [
        ("rootfs", ("rootfs", "hostname"), "changed"),
        ("rootfs", ("rootfs", "extra_apt_sources"), [{"source": "deb x"}]),
        ("rootfs", ("rootfs", "panel_firmware"), {"file": "panel.bin"}),
        ("rootfs", ("storage", "size"), "16G"),
        ("image", ("storage", "size"), "16G"),
        ("boot", ("recovery", "enabled"), True),
        ("bootloader", ("rkbin", "ini_prefix"), "RK3576"),
        ("kernel", ("kernel_device", "board_dts_path"), "board-b.dts"),
    ],
)
def test_实际消费配置变化会改变组件哈希(
        tmp_path: Path, component: str, path: tuple[str, str], value):
    before_config = _config()
    after_config = copy.deepcopy(before_config)
    after_config[path[0]][path[1]] = value

    before = _cache(tmp_path, before_config).compute_hash(component)
    after = _cache(tmp_path, after_config).compute_hash(component)

    assert before != after


def test_builder逻辑变化使组件哈希失效(tmp_path: Path):
    logic = tmp_path / "builder/example.py"
    logic.parent.mkdir(parents=True)
    logic.write_text("VALUE = 1\n")
    before = _cache(tmp_path).compute_hash("kernel")

    logic.write_text("VALUE = 2\n")

    assert before != _cache(tmp_path).compute_hash("kernel")


def test_rootfs_phase_hash覆盖extra_apt_sources(tmp_path: Path):
    before_config = _config()
    after_config = copy.deepcopy(before_config)
    after_config["rootfs"]["extra_apt_sources"] = [{"source": "deb x"}]

    assert (_cache(tmp_path, before_config).compute_phase_hash("rootfs", "base")
            != _cache(tmp_path, after_config).compute_phase_hash(
                "rootfs", "base"))


def test_dynamic_artifact_gates(tmp_path: Path):
    app_config = _config()
    app_config["rootfs"]["custom_packages"] = ["demo", "helper"]
    app_cache = _cache(tmp_path / "app", app_config)
    assert not app_cache._required_artifacts_present("app")
    deb = app_cache.target_dir / "app/demo.deb"
    deb.parent.mkdir(parents=True)
    deb.write_bytes(b"deb")
    assert not app_cache._required_artifacts_present("app")
    (deb.parent / "helper.deb").write_bytes(b"deb")
    assert app_cache._required_artifacts_present("app")

    overlay_config = _config()
    overlay_config["boot"]["vendor_overlays"] = ["demo.dtbo"]
    overlay_cache = _cache(tmp_path / "overlay", overlay_config)
    assert not overlay_cache._required_artifacts_present(
        "device-tree-overlay")
    dtbo = overlay_cache.target_dir / "device-tree-overlay/overlays/demo.dtbo"
    dtbo.parent.mkdir(parents=True)
    dtbo.write_bytes(b"dtbo")
    assert overlay_cache._required_artifacts_present("device-tree-overlay")


def test_qualcomm_bootloader要求所有刷写输入(tmp_path: Path):
    config = _config()
    config["platform"] = "qualcommsc8280xp"
    config["bootloader"] = {
        "edk2_firmware_url": "https://example.com/edk2.zip",
        "firehose_loader": "prog_firehose_ddr.elf",
        "spi_rawprogram": "rawprogram0.xml",
        "spi_patch": "patch0.xml",
        "ufs_firehose": {
            "url": "https://example.com/ufs.elf",
            "filename": "prog_firehose_ufs.elf",
        },
        "ufs_provisions": {
            "default": {
                "url": "https://example.com/provision.xml",
                "filename": "provision.xml",
            }
        },
    }
    cache = _cache(tmp_path, config)
    firmware = cache.target_dir / "bootloader/edk2-spi-firmware"
    firmware.mkdir(parents=True)
    required = cache._required_artifacts("bootloader")
    for relative in required[:-1]:
        (cache.target_dir / "bootloader" / relative).write_bytes(b"asset")
    assert not cache._required_artifacts_present("bootloader")

    (cache.target_dir / "bootloader" / required[-1]).write_bytes(b"asset")

    assert cache._required_artifacts_present("bootloader")


def test_collect拒绝不存在的声明产物(tmp_path: Path):
    engine = BuildEngine(_config(), project_dir=tmp_path)

    with pytest.raises(BuildError, match="构建产物不存在"):
        engine._collect_artifacts("app", {"demo": tmp_path / "missing.deb"})


def test_collect保留已在target中的app产物(tmp_path: Path):
    engine = BuildEngine(_config(), project_dir=tmp_path)
    deb = engine.cache.target_dir / "app/demo.deb"
    deb.parent.mkdir(parents=True)
    deb.write_bytes(b"deb")

    engine._collect_artifacts("app", {"demo": deb})

    assert deb.read_bytes() == b"deb"
