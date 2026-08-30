"""rockchip-multimedia 的单元拆分契约。

这条编译链拆成 8 个单元 App 后，包内不再自建增量机制 —— 每个单元由 flange
的 per-App 缓存独立判定。但拆分引入了两组必须对账的平行声明：

  1. ``app.yaml`` 的 ``build.deps``（flange 用于排序与缓存 Merkle 级联）
     与 ``lib/toolkit.py`` 的 ``Unit.deps``（脚本用于合成 sysroot）；
  2. ``package.py`` 的 component 清单与 ``units/`` 下的实际目录。

任一处漂移都会产生难查的故障：deps 少一条 → 上游变了下游不重编，链出 ABI
不一致的插件；多一条 → 白白重编。这里把两组声明钉在一起。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from builder.app_spec import load_spec
from builder.packages import load_package_manifest
from builder.paths import PROJECT_ROOT

PACKAGE_ROOT = PROJECT_ROOT / "components/packages/rockchip-multimedia"
UNITS_ROOT = PACKAGE_ROOT / "units"


@pytest.fixture(scope="module")
def toolkit(tmp_path_factory, ):
    """加载包内共享构建逻辑（它在导入期就读环境变量）。"""
    tmp = tmp_path_factory.mktemp("rkmm")
    import os

    previous = {
        key: os.environ.get(key)
        for key in ("FLANGE_BUILD_ROOT", "FLANGE_APP_WORK_DIR",
                    "FLANGE_APP_OUTPUT_DIR", "FLANGE_TARGET_ARCH")
    }
    os.environ.update({
        "FLANGE_BUILD_ROOT": str(tmp / "build"),
        "FLANGE_APP_WORK_DIR": str(tmp / "build/work/apps/x/aarch64"),
        "FLANGE_APP_OUTPUT_DIR": str(tmp / "out"),
        "FLANGE_TARGET_ARCH": "aarch64",
    })
    try:
        spec = importlib.util.spec_from_file_location(
            "rkmm_toolkit", PACKAGE_ROOT / "lib/toolkit.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules["rkmm_toolkit"] = module
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop("rkmm_toolkit", None)
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _unit_specs() -> dict:
    return {
        directory.name: load_spec(directory)
        for directory in sorted(UNITS_ROOT.iterdir()) if directory.is_dir()
    }


# ---------------------------------------------------------------------------
# 两组平行声明的对账
# ---------------------------------------------------------------------------

def test_app_yaml与toolkit声明同一组依赖(toolkit):
    """deps 漂移会让上游变化不级联到下游，链出 ABI 不一致的插件。"""
    specs = _unit_specs()
    for name, unit in toolkit.UNITS.items():
        assert name in specs, f"toolkit 声明的单元 {name} 没有 app.yaml"
        assert tuple(specs[name].build.deps) == unit.deps, (
            f"{name} 的 build.deps 与 toolkit.UNITS 不一致")

    assert tuple(specs[toolkit.REPACK_APP].build.deps) == toolkit.REPACK_DEPS


def test_package清单与units目录一致():
    manifest = load_package_manifest("rockchip-multimedia", PROJECT_ROOT)
    declared = {
        component["name"] for component in manifest["components"]
        if component["dir"].startswith("units/")
    }

    assert declared == {d.name for d in UNITS_ROOT.iterdir() if d.is_dir()}


def test_每个单元都声明了共享构建逻辑为哈希输入():
    """lib/ 是 8 个单元共用的构建逻辑，改它必须让全部单元失效。"""
    manifest = load_package_manifest("rockchip-multimedia", PROJECT_ROOT)
    for component in manifest["components"]:
        if not component["dir"].startswith("units/"):
            continue
        assert "lib" in component.get("inputs", []), component["name"]


def test_带补丁的单元声明了自己的补丁目录():
    """补丁在 App 目录之外，不声明就不进哈希 —— 改补丁不会重建。"""
    manifest = load_package_manifest("rockchip-multimedia", PROJECT_ROOT)
    inputs = {
        component["name"]: component.get("inputs", [])
        for component in manifest["components"]
    }
    for unit, patch_dir in (
        ("rkmm-gstreamer", "patches/gstreamer"),
        ("rkmm-gst-base", "patches/gst-plugins-base"),
        ("rkmm-gst-good", "patches/gst-plugins-good"),
        ("rkmm-gst-bad", "patches/gst-plugins-bad"),
    ):
        assert patch_dir in inputs[unit], f"{unit} 未声明 {patch_dir}"
        assert (PACKAGE_ROOT / patch_dir).is_dir()


# ---------------------------------------------------------------------------
# 单元图的结构性约束
# ---------------------------------------------------------------------------

def test_依赖图无环且可拓扑排序(toolkit):
    graph = {name: unit.deps for name, unit in toolkit.UNITS.items()}
    graph[toolkit.REPACK_APP] = toolkit.REPACK_DEPS

    resolved: set[str] = set()
    for _ in range(len(graph)):
        ready = [n for n, deps in graph.items()
                 if n not in resolved and set(deps) <= resolved]
        if not ready:
            break
        resolved.update(ready)

    assert resolved == set(graph), f"无法排序：{set(graph) - resolved}"


def test_每个单元的源都已声明(toolkit):
    known = set(toolkit.GST_SOURCES.values()) | set(toolkit.GIT_SOURCES.values())
    for name, unit in toolkit.UNITS.items():
        assert unit.source in known, f"{name} 引用了未声明的源"


def test_只有产deb的单元声明deb_outputs(toolkit):
    """staging 单元不打 deb，否则空包会被装进 rootfs。"""
    specs = _unit_specs()
    for name, unit in toolkit.UNITS.items():
        spec = specs[name]
        if unit.deb is None:
            assert spec.app.type == "staging", name
            assert not spec.build.deb_outputs, name
        else:
            assert spec.app.type == "vendor", name
            assert spec.build.deb_outputs, name


def test_staging单元声明了产物树(toolkit):
    """staging 树进产物门禁：被删要重建上游，而不是让下游编译失败。"""
    for name, spec in _unit_specs().items():
        if spec.app.type == "staging":
            assert spec.build.staging, name


def test_deb交付总量与拆分前一致(toolkit):
    """拆分不改变交付契约：仍是 17 个 deb。"""
    total = sum(
        len(spec.build.deb_outputs) for spec in _unit_specs().values())
    assert total == 17


def test_repack依赖全部四个gst单元(toolkit):
    """分包边界与编译单元边界不重合，重打必须等四个单元全部就绪。"""
    staging_units = {
        name for name, unit in toolkit.UNITS.items() if unit.deb is None
    }
    assert set(toolkit.REPACK_DEPS) == staging_units
