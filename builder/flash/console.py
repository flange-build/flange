"""刷写 CLI 的终端输出小工具（**宿主机执行期**）。

与构建期无关：这些只在开发者机器上跑 `flange flash` 时用到，因此不进构建
逻辑指纹 —— 改它不该让任何组件失效。
"""

import os
import sys


# ---------------------------------------------------------------------------
# 宿主机 CLI 输出辅助（与 BuildOutput 风格统一）
# ---------------------------------------------------------------------------

def _tty() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

def _c(color: str, text: str) -> str:
    if not _tty():
        return text
    return f"{color}{text}\033[0m"

_BLUE_BOLD = "\033[1;34m"
_GREEN     = "\033[0;32m"
_YELLOW    = "\033[1;33m"
_RED_BOLD  = "\033[1;31m"
_GRAY      = "\033[0;90m"
_WHITE     = "\033[0;37m"

def _header(text: str):
    sep = "═" * 58
    print()
    print(_c(_WHITE, sep))
    print(_c(_WHITE, f" {text}"))
    print(_c(_WHITE, sep))
    print()

def _step(text: str):
    print(_c(_BLUE_BOLD, f"▸ {text}"))

def _ok(text: str):
    print(_c(_GREEN, f"  ✓ {text}"))

def _warn(text: str):
    print(_c(_YELLOW, f"  ⚠ {text}"))

def _err(text: str):
    print(_c(_RED_BOLD, f"  ✗ {text}"))

def _info(text: str):
    print(_c(_GRAY, f"  · {text}"))


