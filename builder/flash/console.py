"""刷写 CLI 的终端输出小工具（**宿主机执行期**）。

与构建期无关：这些只在开发者机器上跑 `flange flash` 时用到，因此不进构建
逻辑指纹 —— 改它不该让任何组件失效。
"""

import sys

from builder.term import Role, style, terminal_width


# ---------------------------------------------------------------------------
# 宿主机 CLI 输出辅助（与 BuildOutput 风格统一）
# ---------------------------------------------------------------------------


def _tty() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _c(role: Role, text: str) -> str:
    return style(text, role, stream=sys.stdout)


def _header(text: str):
    sep = "─" * min(58, terminal_width())
    print()
    print(_c(Role.MUTED, sep))
    print(_c(Role.HEADING, f" {text}"))
    print(_c(Role.MUTED, sep))
    print()


def _step(text: str):
    print(_c(Role.ACTIVE, f"▸ {text}"))


def _ok(text: str):
    print(_c(Role.SUCCESS, f"  ✓ {text}"))


def _warn(text: str):
    print(_c(Role.WARNING, f"  ⚠ {text}"))


def _err(text: str):
    print(_c(Role.ERROR, f"  ✗ {text}"))


def _info(text: str, *, role: Role = Role.MUTED):
    print(_c(role, f"  · {text}"))
