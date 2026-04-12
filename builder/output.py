"""统一构建输出模块 — 分层结构化输出、Spinner、日志持久化。"""

import os
import re
import sys
import time
import threading
from collections import deque
from enum import Enum
from pathlib import Path


# ---------------------------------------------------------------------------
# 输出级别
# ---------------------------------------------------------------------------

class OutputLevel(Enum):
    QUIET = "quiet"      # 仅 L1 摘要行
    NORMAL = "normal"    # L1 + L2 + L3 仅错误（默认）
    VERBOSE = "verbose"  # L1 + L2 + L3 全量


# ---------------------------------------------------------------------------
# ANSI 颜色常量
# ---------------------------------------------------------------------------

class _Colors:
    BLUE_BOLD = "\033[1;34m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    RED_BOLD = "\033[1;31m"
    RED = "\033[0;31m"
    GRAY = "\033[0;90m"
    WHITE = "\033[0;37m"
    RESET = "\033[0m"


_STRIP_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    """移除 ANSI 转义码。"""
    return _STRIP_ANSI_RE.sub("", text)


def _is_tty() -> bool:
    """检测 stdout 是否为 TTY。"""
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


# ---------------------------------------------------------------------------
# 错误检测模式
# ---------------------------------------------------------------------------

ERROR_PATTERNS = [
    re.compile(r"error:", re.IGNORECASE),
    re.compile(r"make\[\d+\]: \*\*\*"),
    re.compile(r"undefined reference to"),
    re.compile(r"^E:", re.MULTILINE),
    re.compile(r"dpkg: error"),
    re.compile(r"fatal:"),
]

WARNING_PATTERNS = [
    re.compile(r"warning:", re.IGNORECASE),
    re.compile(r"^W:", re.MULTILINE),
]

# Spinner 字符集
_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


# ---------------------------------------------------------------------------
# BuildOutput
# ---------------------------------------------------------------------------

class BuildOutput:
    """统一构建输出管理器。

    由 BuildEngine 创建，注入到 DockerRunner 和各 Builder 中。
    负责：分层输出 → 终端显示 + build.log 双写。
    """

    def __init__(self, target_dir: Path, level: OutputLevel = OutputLevel.NORMAL):
        self.target_dir = target_dir
        self.level = level
        self._tty = _is_tty()
        self._lock = threading.Lock()

        # build.log
        target_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = target_dir / "build.log"
        self._log_file = open(self._log_path, "w", encoding="utf-8")

        # 构建计时
        self._build_start_time: float = 0.0
        self._phase_start_time: float = 0.0
        self._current_component: str = ""

        # 各组件结果记录（用于摘要）
        self._results: list[dict] = []

        # 命令输出缓冲
        self._tail_buffer: deque[str] = deque(maxlen=20)
        self._errors: list[str] = []

        # 缩进层级：L1(▸)=0, L2(✓)=1
        self._indent: int = 0

        # Spinner 状态
        self._spinner_event: threading.Event | None = None
        self._spinner_thread: threading.Thread | None = None
        self._spinner_label: str = ""

    def close(self):
        """关闭日志文件。"""
        if self._log_file and not self._log_file.closed:
            self._log_file.close()

    # -----------------------------------------------------------------------
    # 内部写入
    # -----------------------------------------------------------------------

    def _write(self, text: str, *, end: str = "\n", flush: bool = False):
        """写入终端 + 日志文件。"""
        with self._lock:
            sys.stdout.write(text + end)
            if flush:
                sys.stdout.flush()
            self._log_write(strip_ansi(text) + end)

    def _log_write(self, text: str):
        """安全写入日志文件。"""
        try:
            if self._log_file and not self._log_file.closed:
                self._log_file.write(text)
                self._log_file.flush()
        except OSError:
            pass

    def _write_term_only(self, text: str, *, end: str = "", flush: bool = True):
        """仅写终端（用于 spinner \r 刷新）。"""
        with self._lock:
            sys.stdout.write(text + end)
            if flush:
                sys.stdout.flush()

    def _c(self, color: str, text: str) -> str:
        """按 TTY 状态着色。"""
        if not self._tty:
            return text
        return f"{color}{text}{_Colors.RESET}"

    @property
    def _pad(self) -> str:
        """当前缩进前缀：每层 2 空格。"""
        return "  " * (self._indent + 1)

    def indent(self):
        """增加一层缩进（用于子步骤）。"""
        self._indent += 1

    def dedent(self):
        """减少一层缩进。"""
        if self._indent > 0:
            self._indent -= 1

    # -----------------------------------------------------------------------
    # L1: 阶段标题
    # -----------------------------------------------------------------------

    def build_start(self, target: str, config: dict):
        """打印构建横幅。"""
        self._build_start_time = time.time()
        board = config.get("board", "?")
        product = config.get("product", "default")
        variant = config.get("variant", "release")
        banner = f" flange build · {board} · {product}-{variant}"
        sep = "═" * 58
        self._write("")
        self._write(self._c(_Colors.WHITE, sep))
        self._write(self._c(_Colors.WHITE, banner))
        self._write(self._c(_Colors.WHITE, sep))
        self._write("")

    def phase_start(self, component: str):
        """开始一个组件阶段：▸ component"""
        self._current_component = component
        self._phase_start_time = time.time()
        self._tail_buffer.clear()
        self._errors.clear()
        self._indent = 0
        self._write(self._c(_Colors.BLUE_BOLD, f"▸ {component}"))
        self._indent = 1

    def phase_skip(self, component: str):
        """组件跳过：⊘ 无变更，跳过"""
        elapsed = 0.1
        self._write(self._c(_Colors.BLUE_BOLD, f"▸ {component}"))
        self._write(self._c(_Colors.GRAY, f"  ⊘ 无变更，跳过{self._fmt_time_right(elapsed)}"))
        self._indent = 0
        self._write("")
        self._results.append({
            "component": component,
            "status": "skip",
            "elapsed": elapsed,
        })

    def phase_end(self, component: str, *, success: bool = True,
                  error: Exception | None = None):
        """结束组件阶段。"""
        self._spinner_stop_if_running()
        self._indent = 1
        elapsed = time.time() - self._phase_start_time
        if success:
            self._write(self._c(_Colors.GREEN,
                                f"{self._pad}✓ 完成{self._fmt_time_right(elapsed)}"))
        else:
            self._write(self._c(_Colors.RED_BOLD,
                                f"{self._pad}✗ 失败{self._fmt_time_right(elapsed)}"))
            self._show_error_context()
        self._indent = 0
        self._write("")
        self._results.append({
            "component": component,
            "status": "ok" if success else "fail",
            "elapsed": elapsed,
            "error": str(error) if error else None,
        })

    # -----------------------------------------------------------------------
    # L2: 状态行
    # -----------------------------------------------------------------------

    def status(self, msg: str):
        """成功状态：✓ msg"""
        if self.level == OutputLevel.QUIET:
            return
        self._write(self._c(_Colors.GREEN, f"{self._pad}✓ {msg}"))

    def warning(self, msg: str):
        """警告：⚠ msg（仅 VERBOSE）"""
        if self.level != OutputLevel.VERBOSE:
            self._log_write(f"{self._pad}⚠ {msg}\n")
            return
        self._write(self._c(_Colors.YELLOW, f"{self._pad}⚠ {msg}"))

    def error(self, msg: str):
        """错误：✗ msg"""
        self._write(self._c(_Colors.RED_BOLD, f"{self._pad}✗ {msg}"))

    # -----------------------------------------------------------------------
    # L3: 命令输出 (feed_line)
    # -----------------------------------------------------------------------

    def feed_line(self, line: str):
        """处理外部命令的一行输出。"""
        line = line.rstrip("\n\r")

        # 1. 写入日志
        self._log_write(line + "\n")

        # 2. 滚动缓冲
        self._tail_buffer.append(line)

        # 3. 错误检测
        for pat in ERROR_PATTERNS:
            if pat.search(line):
                self._errors.append(line)
                break

        # 4. VERBOSE 模式实时显示
        if self.level == OutputLevel.VERBOSE:
            with self._lock:
                sys.stdout.write(
                    self._c(_Colors.GRAY, f"{self._pad}│ {line}") + "\n")
                sys.stdout.flush()

    # -----------------------------------------------------------------------
    # Spinner
    # -----------------------------------------------------------------------

    def spinner_start(self, label: str):
        """启动 braille spinner + 计时器。"""
        self._spinner_pad = self._pad  # 固定 spinner 启动时的缩进
        if not self._tty or self.level == OutputLevel.QUIET:
            self._log_write(f"{self._spinner_pad}· {label}\n")
            return
        if self.level == OutputLevel.VERBOSE:
            # VERBOSE 模式不用 spinner（输出已全量显示）
            self._write(self._c(_Colors.GRAY, f"{self._spinner_pad}· {label}"))
            return

        self._spinner_label = label
        self._spinner_event = threading.Event()
        self._spinner_thread = threading.Thread(
            target=self._spinner_loop, daemon=True)
        self._spinner_thread.start()

    def spinner_stop(self, *, success: bool = True, label: str = ""):
        """停止 spinner，替换为结果行。"""
        self._spinner_stop_if_running()

    def _spinner_stop_if_running(self):
        if self._spinner_event and not self._spinner_event.is_set():
            self._spinner_event.set()
            if self._spinner_thread:
                self._spinner_thread.join(timeout=1)
            self._spinner_thread = None
            self._spinner_event = None
            # 清除 spinner 行
            if self._tty:
                with self._lock:
                    sys.stdout.write("\r\033[K")
                    sys.stdout.flush()

    def _spinner_loop(self):
        """Spinner 线程主循环。"""
        idx = 0
        start = time.time()
        pad = self._spinner_pad
        while not self._spinner_event.is_set():
            frame = _SPINNER_FRAMES[idx % len(_SPINNER_FRAMES)]
            elapsed = time.time() - start
            line = f"{pad}{frame} {self._spinner_label}  {elapsed:.0f}s"
            if self._tty:
                colored = self._c(_Colors.GRAY, line)
                with self._lock:
                    sys.stdout.write(f"\r\033[K{colored}")
                    sys.stdout.flush()
            idx += 1
            self._spinner_event.wait(0.08)

    # -----------------------------------------------------------------------
    # 构建摘要
    # -----------------------------------------------------------------------

    def build_end(self):
        """打印构建摘要。"""
        self._spinner_stop_if_running()
        total_elapsed = time.time() - self._build_start_time
        has_failure = any(r["status"] == "fail" for r in self._results)

        sep = "─" * 58

        self._write(self._c(_Colors.WHITE, sep))
        if has_failure:
            self._write(self._c(_Colors.RED_BOLD,
                                f" ✗ 构建失败{self._fmt_time_right(total_elapsed, prefix='耗时')}"))
        else:
            self._write(self._c(_Colors.GREEN,
                                f" ✓ 构建完成{self._fmt_time_right(total_elapsed, prefix='总耗时')}"))
        self._write(self._c(_Colors.WHITE, sep))

        # 各组件状态表
        max_elapsed = max((r["elapsed"] for r in self._results), default=1)
        if max_elapsed == 0:
            max_elapsed = 1
        bar_width = 22

        for r in self._results:
            name = r["component"]
            elapsed = r["elapsed"]
            if r["status"] == "skip":
                status_str = self._c(_Colors.GRAY, "跳过")
                time_str = self._c(_Colors.GRAY, f"{elapsed:>5.1f}s")
                bar = ""
            elif r["status"] == "fail":
                status_str = self._c(_Colors.RED_BOLD, "失败")
                time_str = self._c(_Colors.RED_BOLD, f"{elapsed:>5.1f}s")
                bar = ""
                if r.get("error"):
                    bar = self._c(_Colors.RED, f"  → {r['error'][:40]}")
            else:
                status_str = "构建"
                time_str = f"{elapsed:>5.1f}s"
                pct = elapsed / total_elapsed if total_elapsed > 0 else 0
                filled = int(pct * bar_width)
                bar_str = "█" * filled + "░" * (bar_width - filled)
                bar = f"  {bar_str} {pct:>4.0%}"

            self._write(f"  {name:<12}{status_str}  {time_str}{bar}")

        self._write(self._c(_Colors.WHITE, sep))
        self._write(self._c(_Colors.GRAY, f"  日志: {self._log_path}"))
        self._write("")

        self.close()

    # -----------------------------------------------------------------------
    # 错误上下文
    # -----------------------------------------------------------------------

    def _show_error_context(self):
        """显示错误上下文（框线包裹）。"""
        lines = self._errors if self._errors else list(self._tail_buffer)
        if not lines:
            return
        # 最多显示 15 行
        lines = lines[-15:]
        pad = self._pad
        border = self._c(_Colors.RED, f"{pad}" + "┄" * 50)
        self._write(border)
        for line in lines:
            self._write(self._c(_Colors.RED, f"{pad}{line}"))
        self._write(border)

    # -----------------------------------------------------------------------
    # 工具
    # -----------------------------------------------------------------------

    def _fmt_time_right(self, seconds: float, *, prefix: str = "") -> str:
        """格式化耗时（右侧灰色）。"""
        label = f"{prefix} " if prefix else ""
        return self._c(_Colors.GRAY, f"  {label}{seconds:.1f}s")
