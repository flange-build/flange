"""补丁路由的通用配置辅助。"""

from __future__ import annotations


def normalize_excluded_patches(value, field: str) -> tuple[str, ...]:
    """校验并规范化 ``exclude_patches``，供配置、cache 与 builder 共用。"""
    if value is None:
        return ()
    if not isinstance(value, (list, tuple, set)):
        raise TypeError(f"{field} 必须是字符串列表")
    if any(not isinstance(item, str) or not item for item in value):
        raise TypeError(f"{field} 必须是非空字符串列表")
    return tuple(value)
