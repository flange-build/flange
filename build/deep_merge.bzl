"""Starlark dict 深度合并工具"""

def deep_merge(base, override):
    """深度合并两个 dict，override 中的值覆盖 base 中的同名 key。

    合并规则：
    - dict 类型递归合并
    - 非 dict 类型（string、list、bool 等）后者直接覆盖前者
    - base 中存在但 override 中不存在的 key 保留

    Args:
        base: 基础 dict
        override: 覆盖 dict

    Returns:
        合并后的新 dict，不修改输入参数
    """
    result = {}
    for key in base:
        if key in override:
            if type(base[key]) == "dict" and type(override[key]) == "dict":
                result[key] = deep_merge(base[key], override[key])
            else:
                result[key] = override[key]
        else:
            result[key] = base[key]
    for key in override:
        if key not in base:
            result[key] = override[key]
    return result
