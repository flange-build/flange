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
from types import ModuleType
from typing import Any, Protocol, runtime_checkable


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


def load(platform: str, layer_stack=None) -> ModuleType:
    """按平台名加载平台包。"""
    if layer_stack is not None:
        module = layer_stack.provider("platform", platform)
        if module is not None:
            missing = missing_attrs(module)
            if missing:
                raise ValueError(f"平台策略 {platform} 缺少接口：{', '.join(missing)}")
            return module
    return importlib.import_module(f"builder.platforms.{platform}")


def load_for(config: dict) -> ModuleType:
    platform = config.get("platform", "")
    if not platform:
        raise ValueError("config 缺少 platform 字段")
    return load(platform, getattr(config, "layer_stack", None))


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


def known_platforms(layer_stack=None) -> list[str]:
    """磁盘上已注册的平台包名。"""
    from pathlib import Path

    root = Path(__file__).parent
    builtin = {
        entry.name for entry in root.iterdir()
        if entry.is_dir() and entry.name != "__pycache__"
        and (entry / "__init__.py").is_file()
    }
    if layer_stack is not None:
        builtin.update(provider.name for layer in layer_stack.layers
                       for provider in layer.providers if provider.kind == "platform")
    return sorted(builtin)


def missing_attrs(module: ModuleType) -> list[str]:
    """返回平台包缺失的契约符号；空列表表示符合契约。"""
    return [attr for attr in REQUIRED_ATTRS if not hasattr(module, attr)]


def conforms(module: ModuleType) -> bool:
    return not missing_attrs(module)
