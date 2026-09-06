"""Package 与 App 共用的生命周期 action 校验。"""

from __future__ import annotations

from typing import Any


VALID_ACTIONS = frozenset({"build", "deploy", "run", "debug", "log", "test"})


def validate_actions(
    raw: Any,
    *,
    field: str = "actions",
) -> dict[str, list[str]]:
    """校验 action 名到 argv 的映射，并返回独立副本。

    action 必须使用 argv 数组表达，调用方可以直接交给 ``subprocess``，无需
    shell 拆词或展开。数组及其中每个参数都必须非空。
    """
    if not isinstance(raw, dict):
        raise ValueError(f"{field} 必须是 action 名到 argv 数组的字典")

    actions: dict[str, list[str]] = {}
    for name, argv in raw.items():
        if not isinstance(name, str) or name not in VALID_ACTIONS:
            raise ValueError(
                f"{field} 包含未知 action {name!r}；允许值：{', '.join(sorted(VALID_ACTIONS))}"
            )
        if not isinstance(argv, list):
            raise ValueError(f"{field}.{name} 必须是非空字符串 argv 列表")
        if not argv:
            raise ValueError(f"{field}.{name} 的 argv 不能为空")
        for index, argument in enumerate(argv):
            if not isinstance(argument, str) or not argument.strip() or "\0" in argument:
                raise ValueError(f"{field}.{name}[{index}] 必须是非空字符串")
        actions[name] = list(argv)

    return actions
