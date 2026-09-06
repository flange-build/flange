"""终端呈现的基础能力。

宽度、配色支持、中文宽度、进度条渲染 —— 输出层与 `lunch` 界面都要用，各写
一份必然漂移（中文宽度算错的表现是列错位，而错位只在有中文的那几行出现，
很难在开发时注意到）。

**降级是这里的第一约束**：同一份构建可能跑在交互终端、CI 日志、`| tee`
之后的管道里。凡是依赖光标控制或颜色的能力，都必须在非 TTY 下自动退化成
纯文本，且退化后的内容不丢信息。
"""

from __future__ import annotations

import os
import shutil
import sys
import unicodedata
from enum import Enum
from types import MappingProxyType

#: 终端宽度取不到时的兜底。80 太窄会让摘要表频繁折行，100 更贴近现代终端。
DEFAULT_WIDTH = 100

#: 宽度上限：超宽终端上把内容拉满整行反而难读（眼睛要横扫）。
MAX_WIDTH = 120


class Role(Enum):
    """信息的含义；调用者选择语义，不自行决定终端颜色。"""

    HEADING = "heading"
    ACTIVE = "active"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    PATH = "path"
    COMMAND = "command"
    MUTED = "muted"
    TEXT = "text"


# 使用终端基础色，让用户的明暗主题决定具体色值；正文不强制白色或背景色。
ANSI_STYLES = MappingProxyType(
    {
        Role.HEADING: "1;34",
        Role.ACTIVE: "34",
        Role.SUCCESS: "32",
        Role.WARNING: "33",
        Role.ERROR: "1;31",
        Role.PATH: "36",
        Role.COMMAND: "36",
        Role.MUTED: "2",
        Role.TEXT: "",
    }
)


def terminal_width() -> int:
    """当前终端宽度，限制在可读范围内。"""
    try:
        columns = shutil.get_terminal_size((DEFAULT_WIDTH, 24)).columns
    except OSError:
        columns = DEFAULT_WIDTH
    return max(1, min(columns, MAX_WIDTH))


def is_tty(stream=None) -> bool:
    stream = stream or sys.stdout
    return hasattr(stream, "isatty") and stream.isatty()


def supports_color(stream=None) -> bool:
    """是否应当输出 ANSI 颜色。

    尊重 `NO_COLOR`（https://no-color.org）与 `TERM=dumb` —— 用户把输出
    重定向到文件或在不支持的终端里跑时，颜色码会变成满屏乱码。
    """
    if "NO_COLOR" in os.environ:
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    return is_tty(stream)


def style(text: object, role: Role, *, stream=None) -> str:
    """仅为支持颜色的实际输出流添加样式；纯文本内容和换行保持不变。"""
    value = str(text)
    code = ANSI_STYLES[role]
    if not value or not code or not supports_color(stream):
        return value
    return f"\033[{code}m{value}\033[0m"


# ---------------------------------------------------------------------------
# 宽度：中文是双宽字符
# ---------------------------------------------------------------------------


def _character_width(character: str) -> int:
    if unicodedata.combining(character) or unicodedata.category(character) in {
        "Cf",
        "Mn",
        "Me",
    }:
        return 0
    return 2 if unicodedata.east_asian_width(character) in ("W", "F") else 1


def display_width(text: str) -> int:
    """字符串在终端上占的列数。

    中文、全角标点占两列。按 len() 算会让表格错位、让截断切出半个字符 ——
    而且只在含中文的那几行出错，开发时很容易漏掉。
    """
    return sum(_character_width(ch) for ch in text)


def truncate(text: str, width: int) -> str:
    """按显示宽度截断，宽度不足时不留半个字符。"""
    if width <= 0:
        return ""
    if display_width(text) <= width:
        return text
    out: list[str] = []
    used = 0
    for ch in text:
        step = _character_width(ch)
        if used + step > width - 1:
            break
        out.append(ch)
        used += step
    return "".join(out) + "…"


def pad(text: str, width: int) -> str:
    """按显示宽度右侧补空格。"""
    return text + " " * max(0, width - display_width(text))


def rpad(text: str, width: int) -> str:
    """按显示宽度左侧补空格（右对齐）。"""
    return " " * max(0, width - display_width(text)) + text


# ---------------------------------------------------------------------------
# 图形元素
# ---------------------------------------------------------------------------


def progress_bar(fraction: float, width: int) -> str:
    """进度条：已完成用实线，进行中的那一格用端点符，未完成用细线。

    端点符（╸）让"当前位置"一眼可见，而不是只能靠实线的边界去猜。
    """
    width = max(4, width)
    fraction = max(0.0, min(1.0, fraction))
    filled = int(fraction * width)
    if filled >= width:
        return "━" * width
    head = "╸" if filled > 0 or fraction > 0 else ""
    body = "━" * max(0, filled - (1 if head else 0))
    rest = "─" * (width - len(body) - len(head))
    return f"{body}{head}{rest}"


def duration_bar(fraction: float, width: int) -> str:
    """耗时占比条 —— **刻意与进度条不同形**。

    构建摘要里的条表示"这个组件占了多少时间"，不是进度。用同一套字形会被
    读成进度条（原实现正是如此），所以这里换成方块。
    """
    width = max(4, width)
    fraction = max(0.0, min(1.0, fraction))
    filled = round(fraction * width)
    return "▰" * filled + "▱" * (width - filled)


def format_duration(seconds: float) -> str:
    """人读的耗时：秒级给一位小数，分钟以上给 `XmYs`。

    2338.4s 这种数字要用户自己心算成 39 分钟 —— 摘要里最该一眼看懂的就是
    "哪一步花了最久"。
    """
    if seconds < 0:
        seconds = 0
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, rest = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m{rest:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def wrap(text: str, width: int) -> list[str]:
    """按显示宽度折行，不切断字符。

    用于**不能截断**的内容（异常原文）：截断会把定位问题最关键的那句话
    砍掉一半，而超宽会让终端自己在任意位置折，破坏缩进对齐。
    """
    if width <= 0:
        return [text]
    lines: list[str] = []
    current: list[str] = []
    used = 0
    for ch in text:
        step = _character_width(ch)
        if used + step > width and current:
            lines.append("".join(current))
            current, used = [], 0
        current.append(ch)
        used += step
    if current:
        lines.append("".join(current))
    return lines or [""]
