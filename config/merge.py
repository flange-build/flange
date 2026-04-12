"""配置合并引擎。

实现三层配置继承（platform → SoC → board）的深度合并，
支持 +key 追加语义和条件标记（:variant / :product）解析。
"""

import copy
from typing import Any


def deep_merge(base: dict, override: dict) -> dict:
    """将 override 深度合并到 base 上，返回新字典。

    合并规则：
    - 标量（str/int/bool）：override 替换 base
    - dict：递归深度合并
    - list：override 完全替换 base（非追加）
    - +key（列表）：追加到 base 中对应的 key 列表；若 base 无该 key，则原样保留
    - +key:condition：同名条件键追加；否则原样保留

    不修改输入字典。
    """
    result = copy.deepcopy(base)
    override = copy.deepcopy(override)

    for key, value in override.items():
        if key.startswith("+"):
            _handle_append_key(result, key, value)
        elif key in result and isinstance(result[key], dict) and isinstance(value, dict):
            # 字典递归合并
            result[key] = deep_merge(result[key], value)
        else:
            # 标量或列表：直接覆盖
            result[key] = value

    return result


def _handle_append_key(result: dict, plus_key: str, value: Any) -> None:
    """处理 +key 追加逻辑（就地修改 result）。

    plus_key 形如 "+packages" 或 "+packages:debug"。
    """
    # 解析："+packages:debug" → base_key="packages", condition="debug"
    stripped = plus_key[1:]  # 去掉 "+"
    colon_pos = stripped.find(":")
    if colon_pos >= 0:
        base_key = stripped[:colon_pos]
        # 带条件的 +key
        # 检查 base 中是否有同名 +key:condition（合并）
        if plus_key in result and isinstance(result[plus_key], list) and isinstance(value, list):
            result[plus_key] = result[plus_key] + value
        else:
            result[plus_key] = value
    else:
        base_key = stripped
        # 无条件 +key：尝试追加到 base 的 base_key 列表，或深度合并到 base 的 dict
        if base_key in result and isinstance(result[base_key], list) and isinstance(value, list):
            result[base_key] = result[base_key] + value
        elif base_key in result and isinstance(result[base_key], dict) and isinstance(value, dict):
            # 字典追加合并：将 +key 的内容深度合并到 base_key
            result[base_key] = deep_merge(result[base_key], value)
        else:
            # base 无对应 key，原样保留
            result[plus_key] = value


def resolve_conditions(config: dict, product: str, variant: str) -> dict:
    """解析条件标记，返回扁平化的配置字典。

    处理顺序：
    1. 无条件键（无 + 前缀、无 : 后缀）
    2. 无条件 +key 追加
    3. 匹配的条件键（覆盖或追加）

    不修改输入字典。
    """
    config = copy.deepcopy(config)
    result: dict[str, Any] = {}

    # 分类所有键
    unconditional: dict[str, Any] = {}        # 普通键
    unconditional_appends: dict[str, Any] = {}  # +key（无条件追加）
    conditional: list[tuple[str, str, str, bool, Any]] = []
    # conditional 元素：(原始键, base_key, condition, is_append, value)

    for key, value in config.items():
        is_append = key.startswith("+")
        stripped = key[1:] if is_append else key
        colon_pos = stripped.find(":")

        if colon_pos >= 0:
            # 带条件
            base_key = stripped[:colon_pos]
            condition = stripped[colon_pos + 1:]
            conditional.append((key, base_key, condition, is_append, value))
        elif is_append:
            # 无条件追加
            base_key = stripped
            unconditional_appends[base_key] = value
        else:
            # 普通无条件键
            unconditional[key] = value

    # 第 1 步：无条件键
    for key, value in unconditional.items():
        if isinstance(value, dict):
            # 递归处理嵌套字典
            result[key] = resolve_conditions(value, product=product, variant=variant)
        else:
            result[key] = value

    # 第 2 步：无条件 +key 追加
    for base_key, value in unconditional_appends.items():
        if base_key in result and isinstance(result[base_key], list) and isinstance(value, list):
            result[base_key] = result[base_key] + value
        elif base_key in result and isinstance(result[base_key], dict) and isinstance(value, dict):
            # 字典追加合并后递归解析条件
            merged = deep_merge(result[base_key], value)
            result[base_key] = resolve_conditions(merged, product=product, variant=variant)
        else:
            result[base_key] = value

    # 第 3 步：匹配的条件键
    for _orig_key, base_key, condition, is_append, value in conditional:
        if condition not in (product, variant):
            # 条件不匹配，丢弃
            continue

        if is_append:
            # 条件追加
            if base_key in result and isinstance(result[base_key], list) and isinstance(value, list):
                result[base_key] = result[base_key] + value
            else:
                result[base_key] = value
        else:
            # 条件覆盖
            result[base_key] = value

    # 将当前 product/variant 写入结果，供构建/刷写流程使用
    result["product"] = product
    result["variant"] = variant

    return result
