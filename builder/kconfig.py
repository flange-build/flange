"""Kernel 与 Bootloader 共用的 canonical Kconfig 语义。"""

from __future__ import annotations

import re
from pathlib import Path


_SYMBOL_RE = re.compile(r"^CONFIG_[A-Za-z0-9_]+$")


def defconfig_targets(value, field: str) -> list[str]:
    """校验并返回只包含 make target/fragment 的有序数组。"""
    if not isinstance(value, list):
        raise ValueError(f"{field} 必须是字符串数组")
    for item in value:
        if not isinstance(item, str) or not item:
            raise ValueError(f"{field} 必须是非空字符串数组")
        if "=" in item or item.lstrip().startswith("# CONFIG_"):
            raise ValueError(f"{field} 不得包含 raw Kconfig，请改用 config 对象")
    return list(value)


def render_kconfig(values: dict | None, field: str) -> list[str]:
    """把 symbol → 右值对象确定性渲染为 Kconfig 行。"""
    if values is None:
        return []
    if not isinstance(values, dict):
        raise ValueError(f"{field} 必须是字典")
    lines: list[str] = []
    for symbol in sorted(values):
        value = values[symbol]
        if not _SYMBOL_RE.fullmatch(symbol):
            raise ValueError(f"{field} 包含非法 symbol: {symbol!r}")
        if not isinstance(value, str) or not value or "\n" in value:
            raise ValueError(f"{field}.{symbol} 必须是单行 Kconfig 右值")
        if value == "n":
            lines.append(f"# {symbol} is not set")
        else:
            lines.append(f"{symbol}={value}")
    return lines


def write_kconfig_fragment(
    path: Path,
    values: dict | None,
    *,
    field: str,
) -> int:
    """写入 canonical Kconfig fragment，返回 symbol 数量。"""
    lines = render_kconfig(values, field)
    if not lines:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# 由 flange canonical config 自动生成，请勿手工修改\n"
        + "\n".join(lines)
        + "\n"
    )
    return len(lines)
