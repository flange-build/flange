"""平台包契约。

每个 `builder/platforms/<name>/` 是一个插件包。此前它的契约完全靠约定：
`ARTIFACT_NAMES` 与 `create_builder` 两个符号散落在四份 `__init__.py` 里，
没有任何一处校验；漏一个的后果是 `AttributeError`，而且要等到构建跑到那个
组件才炸。

同样没有落点的还有**平台能力**。判断"这个平台构建期合并 DTBO 还是运行期加载
overlay"，此前在两个文件里各写了一遍 `platform.startswith("qualcomm")` ——
把能力和命名绑死：新增一个走构建期合并的非高通平台，两处都得改，漏一处就是
静默的错误分支。能力应当由平台自己声明。

这个模块把契约写成代码：`PlatformSpec` 是文档化的 Protocol，`conforms` 用于
测试里做符合性检查，`capability` 是能力读取的唯一入口。
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol, runtime_checkable

from builder.artifacts import ArtifactSpec


@runtime_checkable
class PlatformSpec(Protocol):
    """平台包必须提供的符号。"""

    #: ``(component, format) -> 产物文件名``，供 engine 收集产物。
    ARTIFACT_NAMES: dict

    def create_builder(self, component: str, docker, source):  # noqa: D102
        ...


#: 平台可选声明的能力开关：名字 → 默认值。
#:
#: 默认值是**多数派行为**，这样新增平台只需要声明自己偏离的部分。
CAPABILITIES: dict[str, Any] = {
    # 构建期把 DTBO 合并进 DTB（fdtoverlay），而不是运行期由 bootloader 加载。
    # 高通的 bootloader 不做运行期 overlay，所以它们声明 True。
    "dtbo_merge_at_build": False,
}

#: 契约中必须存在的符号。
REQUIRED_ATTRS = ("ARTIFACT_NAMES", "create_builder")


def load(platform: str) -> ModuleType:
    """按平台名加载平台包。"""
    return importlib.import_module(f"builder.platforms.{platform}")


def load_for(config: dict) -> ModuleType:
    platform = config.get("platform", "")
    if not platform:
        raise ValueError("config 缺少 platform 字段")
    return load(platform)


def capability(config: dict, name: str) -> Any:
    """读取当前平台的能力开关。

    平台未声明该能力时返回 `CAPABILITIES` 里的默认值 —— 平台包只需要写出
    自己偏离多数派的那几条。

    `platform` 缺失或没有对应平台包时同样返回默认值：能力查询是**查询**不是
    校验。平台名拼错的检查归 `validate_platform`（校验），放在那里既不会让
    每个能力查询点都硬依赖平台包可导入，报错也比 ModuleNotFoundError 好读。
    """
    if name not in CAPABILITIES:
        raise KeyError(f"未知的平台能力: {name}（可选: {sorted(CAPABILITIES)}）")
    if not config.get("platform"):
        return CAPABILITIES[name]
    try:
        module = load_for(config)
    except ModuleNotFoundError:
        return CAPABILITIES[name]
    return getattr(module, name.upper(), CAPABILITIES[name])


def known_platforms() -> list[str]:
    """磁盘上已注册的平台包名。"""
    from pathlib import Path

    root = Path(__file__).parent
    return sorted(
        entry.name for entry in root.iterdir()
        if entry.is_dir() and entry.name != "__pycache__"
        and (entry / "__init__.py").is_file()
    )


def missing_attrs(module: ModuleType) -> list[str]:
    """返回平台包缺失的契约符号；空列表表示符合契约。"""
    return [attr for attr in REQUIRED_ATTRS if not hasattr(module, attr)]


def conforms(module: ModuleType) -> bool:
    return not missing_attrs(module)


def _optional_platform(config: Mapping) -> ModuleType | None:
    """允许不带平台的纯计划夹具，不吞掉真实平台内部的导入错误。"""
    platform = config.get("platform")
    if not platform:
        return None
    try:
        return load(platform)
    except ModuleNotFoundError as error:
        if error.name == f"builder.platforms.{platform}":
            return None
        raise


def dependency_graph(config: Mapping, base: Mapping | None = None) -> dict[str, list[str]]:
    """在基础图上追加平台依赖，规划、执行和指纹共用同一声明。"""
    from builder.graph import DEPENDENCY_GRAPH, topological_order

    source = base if base is not None else DEPENDENCY_GRAPH
    graph = {name: list(deps) for name, deps in source.items()}
    module = _optional_platform(config)
    extra = getattr(module, "EXTRA_DEPENDENCIES", {})
    if not isinstance(extra, dict):
        raise ValueError("平台 EXTRA_DEPENDENCIES 必须是组件到依赖列表的映射")
    for component, dependencies in extra.items():
        if component not in graph:
            raise ValueError(f"平台声明未知组件: {component}")
        if not isinstance(dependencies, (list, tuple)) or any(
            not isinstance(name, str) for name in dependencies
        ):
            raise ValueError(f"平台 {component} 依赖必须是字符串列表")
        if len(set(dependencies)) != len(dependencies):
            raise ValueError(f"平台 {component} 包含重复依赖")
        for name in dependencies:
            if name not in graph:
                raise ValueError(f"平台 {component} 依赖未知组件: {name}")
            if name not in graph[component]:
                graph[component].append(name)
    topological_order(graph, tuple(graph))
    return graph


def required_artifacts(
    component: str, root: Path, config: dict
) -> tuple[ArtifactSpec, ...] | None:
    """平台可覆盖组件输出契约；None 表示使用原有默认契约。"""
    module = _optional_platform(config)
    hook = getattr(module, "required_artifacts", None)
    if hook is None:
        return None
    if not callable(hook):
        raise ValueError("平台 required_artifacts 必须可调用")
    outputs = hook(component, root, config)
    if outputs is None:
        return None
    if not isinstance(outputs, (list, tuple)) or not outputs:
        raise ValueError(f"平台 {component} 必需产物必须是非空列表")
    names, paths = set(), set()
    for output in outputs:
        if not isinstance(output, ArtifactSpec):
            raise ValueError(f"平台 {component} 产物必须使用 ArtifactSpec")
        path = output.path
        if ".." in path.parts or not path.is_relative_to(root.absolute()) or path == root.absolute():
            raise ValueError(f"平台 {component} 产物路径超出组件目录: {path}")
        if output.name in names or path in paths:
            raise ValueError(f"平台 {component} 包含重复产物: {output.name}")
        names.add(output.name)
        paths.add(path)
    return tuple(outputs)
