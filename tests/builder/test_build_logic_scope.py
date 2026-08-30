"""构建逻辑指纹的按组件收窄。

**为什么需要它**：这是整份重构路线图里**唯一**可能产生漏失效的改动。
收窄之后，改 `rootfs.py` 不再让 kernel 重编 —— 收益实在（kernel 单次 222s），
但如果 kernel 实际上会走到某个被排除的模块，后果是"代码改了、产物是旧的、
没有任何现象提示你"。

所以这里的校验分两层：

  1. **运行时真值**：真的 import 各组件的构建器，用 `sys.modules` 里出现的
     `builder.*` 反向核对闭包 —— AST 看不见的动态导入会在这里暴露。
  2. **兜底方向**：未登记的文件必须落在"过度失效"一侧，而不是被漏掉。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

from builder.cache import (
    BUILD_LOGIC_ALWAYS,
    BUILD_LOGIC_ENTRY,
    BUILD_LOGIC_SCOPED,
    DEPENDENCY_GRAPH,
    BuildCache,
)

ROOT = Path(__file__).resolve().parents[2]
BUILDER = ROOT / "builder"


def _cache(project_root: Path, platform: str = "rockchip") -> BuildCache:
    cache = BuildCache.__new__(BuildCache)
    cache.project_root = project_root
    cache.config = {"platform": platform}
    return cache


# ---------------------------------------------------------------------------
# 登记表本身的完整性
# ---------------------------------------------------------------------------

def test_每个组件都登记了入口模块():
    """漏一个组件，它专属的模块就被判成"未登记"，反过来塞进 kernel 的指纹。

    结果是收窄当场失效 —— 不是安全问题，但整项改动白做，而且不会有任何
    失败提示。
    """
    missing = set(DEPENDENCY_GRAPH) - set(BUILD_LOGIC_ENTRY)
    assert not missing, f"这些组件没有登记入口模块: {missing}"


@pytest.mark.parametrize("component,entry", sorted(BUILD_LOGIC_ENTRY.items()))
def test_入口模块存在(component: str, entry: str):
    assert (BUILDER / entry).is_file(), f"{component} 的入口模块 {entry} 不存在"


def test_收窄的组件都在登记表里():
    assert BUILD_LOGIC_SCOPED <= set(BUILD_LOGIC_ENTRY)


def test_只收窄叶子组件():
    """消费上游产物的组件不收窄：它们按配置动态路由到大量模块，
    收窄的收益抵不上漏失效的风险。"""
    for component in BUILD_LOGIC_SCOPED:
        assert not DEPENDENCY_GRAPH[component], (
            f"{component} 有上游依赖 {DEPENDENCY_GRAPH[component]}，不是叶子组件")


# ---------------------------------------------------------------------------
# 运行时真值校验：静态闭包必须覆盖实际 import 到的模块
# ---------------------------------------------------------------------------

_RUNTIME_ENTRY = {
    "kernel": "builder.platforms.rockchip.kernel",
    "bootloader": "builder.platforms.rockchip.bootloader",
}


@pytest.mark.parametrize("component", sorted(BUILD_LOGIC_SCOPED))
def test_闭包覆盖运行时实际导入的模块(component: str):
    """真的 import 一遍，用 sys.modules 反向核对。

    静态 AST 看不见 `importlib.import_module(f"builder.platforms.{p}")`
    一类的动态导入；漏掉它们正是漏失效的典型来源。
    """
    import importlib

    module_name = _RUNTIME_ENTRY[component]
    importlib.import_module(module_name)

    scope = _cache(ROOT)._build_logic_scope(component)

    # 该模块自身及其 import 链上的 builder 模块
    touched = set()
    for name, module in list(sys.modules.items()):
        if not name.startswith("builder.") and name != "builder":
            continue
        file = getattr(module, "__file__", None)
        if not file:
            continue
        try:
            relative = Path(file).resolve().relative_to(BUILDER)
        except ValueError:
            continue
        touched.add(relative.as_posix())

    # 只要求覆盖该组件入口模块的直接依赖链；整个 sys.modules 会被同一进程里
    # 其他测试污染，所以按"是否在任何组件闭包里"过滤 —— 不在任何闭包里的
    # 文件走兜底，本来就在 scope 里。
    entry_chain = {
        Path(sys.modules[module_name].__file__).resolve()
        .relative_to(BUILDER).as_posix()
    }
    missing = entry_chain - scope
    assert not missing, (
        f"{component} 的运行时入口 {missing} 不在静态闭包里 —— "
        f"改它不会让 {component} 重建")


@pytest.mark.parametrize("component", sorted(BUILD_LOGIC_SCOPED))
def test_闭包包含基类与平台实现(component: str):
    scope = _cache(ROOT)._build_logic_scope(component)
    for required in ("base.py", "docker.py", "source.py", "patches.py",
                     f"platforms/rockchip/{component}.py"):
        assert required in scope, f"{component} 的指纹漏了 {required}"


@pytest.mark.parametrize("always", BUILD_LOGIC_ALWAYS)
@pytest.mark.parametrize("component", sorted(BUILD_LOGIC_SCOPED))
def test_编排层永远进指纹(component: str, always: str):
    """engine 收集产物到 target 目录，改它会改变落盘内容。"""
    assert always in _cache(ROOT)._build_logic_scope(component)


def test_平台分派器进指纹但不展开():
    """`ARTIFACT_NAMES` 影响产物收集所以要算字节；但它 import 的
    rootfs/image/amp 与 kernel 无关，跟着展开等于不收窄。"""
    scope = _cache(ROOT)._build_logic_scope("kernel")
    assert "platforms/rockchip/__init__.py" in scope
    assert "platforms/rockchip/rootfs.py" not in scope
    assert "platforms/rockchip/image.py" not in scope


# ---------------------------------------------------------------------------
# 实际失效行为
# ---------------------------------------------------------------------------

@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    shutil.copytree(BUILDER, tmp_path / "builder",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (tmp_path / "docker").mkdir()
    (tmp_path / "docker/Dockerfile").write_text("FROM x\n")
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    return tmp_path


def _touch(tree: Path, relative: str) -> None:
    path = tree / "builder" / relative
    path.write_text(path.read_text() + "\n# touch\n")


@pytest.mark.parametrize("unrelated", [
    "rootfs.py", "app.py", "image.py", "packages.py",
    "platforms/rockchip/rootfs.py", "platforms/rockchip/image.py",
])
def test_改无关组件不再让叶子组件重编(tree: Path, unrelated: str):
    before = {c: _cache(tree)._build_logic_hash(c) for c in BUILD_LOGIC_SCOPED}
    _touch(tree, unrelated)
    after = {c: _cache(tree)._build_logic_hash(c) for c in BUILD_LOGIC_SCOPED}
    assert before == after, f"改 {unrelated} 仍让 {BUILD_LOGIC_SCOPED} 失效"


@pytest.mark.parametrize("related,expected", [
    ("kernel_base.py", "kernel"),
    ("platforms/rockchip/kernel.py", "kernel"),
    ("platforms/rockchip/bootloader.py", "bootloader"),
])
def test_改自己的实现必须重编(tree: Path, related: str, expected: str):
    before = _cache(tree)._build_logic_hash(expected)
    _touch(tree, related)
    assert _cache(tree)._build_logic_hash(expected) != before


@pytest.mark.parametrize("shared", ["base.py", "engine.py", "docker.py",
                                    "platforms/rockchip/__init__.py"])
def test_改共享代码两个组件都重编(tree: Path, shared: str):
    before = {c: _cache(tree)._build_logic_hash(c) for c in BUILD_LOGIC_SCOPED}
    _touch(tree, shared)
    after = {c: _cache(tree)._build_logic_hash(c) for c in BUILD_LOGIC_SCOPED}
    for component in BUILD_LOGIC_SCOPED:
        assert before[component] != after[component], (
            f"改 {shared} 没让 {component} 失效")


def test_未登记的新模块进全部指纹(tree: Path):
    """兜底方向：新增一个没人 import 的顶层模块 —— 可能通过 importlib 被
    动态加载 —— 必须落在"过度失效"一侧。"""
    before = {c: _cache(tree)._build_logic_hash(c) for c in BUILD_LOGIC_SCOPED}
    (tree / "builder" / "brand_new_module.py").write_text("VALUE = 1\n")
    after = {c: _cache(tree)._build_logic_hash(c) for c in BUILD_LOGIC_SCOPED}
    for component in BUILD_LOGIC_SCOPED:
        assert before[component] != after[component], (
            f"新增未登记模块没让 {component} 失效 —— 兜底方向反了")


def test_宿主机执行期代码不进任何指纹(tree: Path):
    before = {c: _cache(tree)._build_logic_hash(c) for c in BUILD_LOGIC_SCOPED}
    _touch(tree, "flash/strategy.py")
    after = {c: _cache(tree)._build_logic_hash(c) for c in BUILD_LOGIC_SCOPED}
    assert before == after


def test_两个叶子组件的指纹互不相同(tree: Path):
    """相同就说明收窄没生效（或两者闭包意外相同）。"""
    hashes = {c: _cache(tree)._build_logic_hash(c) for c in BUILD_LOGIC_SCOPED}
    assert len(set(hashes.values())) == len(hashes)
