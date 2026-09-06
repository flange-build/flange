"""统一构建输出模块 — 分层结构化输出、Spinner、日志持久化。"""

import os
import re
import shlex
import sys
import time
import threading
import traceback
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from builder.term import (
    Role,
    format_duration,
    style,
    supports_color,
    terminal_width,
    truncate,
    wrap,
)


# ---------------------------------------------------------------------------
# 输出级别
# ---------------------------------------------------------------------------

class OutputLevel(Enum):
    QUIET = "quiet"      # 仅 L1 摘要行
    NORMAL = "normal"    # L1 + L2 + L3 仅错误（默认）
    VERBOSE = "verbose"  # L1 + L2 + L3 全量


@dataclass(frozen=True)
class CommandDiagnostic:
    """失败发生时的命令与诊断；后续清理不能改变这份快照。"""

    command: tuple[str, ...]
    lines: tuple[str, ...]


# ---------------------------------------------------------------------------
# ANSI 颜色清理
# ---------------------------------------------------------------------------

_STRIP_ANSI_RE = re.compile(
    r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]|\x1b[@-_]"
)


def strip_ansi(text: str) -> str:
    """移除 ANSI 转义码。"""
    return _STRIP_ANSI_RE.sub("", text).replace("\r", "").replace("\b", "")


def _display_len(text: str) -> int:
    """去掉 ANSI 后的显示宽度 —— 底栏要按可见宽度对齐，不能把颜色码算进去。"""
    from builder.term import display_width

    return display_width(strip_ansi(text))


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
    re.compile(r"\b(permission denied|operation not permitted|read-only file system|no space left on device)\b",
               re.IGNORECASE),
]

WARNING_PATTERNS = [
    re.compile(r"warning:", re.IGNORECASE),
    re.compile(r"^W:", re.MULTILINE),
]

# Spinner 字符集
_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


# ---------------------------------------------------------------------------
# build.log 轮转
# ---------------------------------------------------------------------------

#: 保留多少份历史 build.log。构建失败后经常要跟上一次成功的构建对比，而
#: 之前每次构建都直接 truncate，上一次的日志当场消失。
DEFAULT_LOG_KEEP = 3
LOG_KEEP_ENV = "FLANGE_LOG_KEEP"


def _log_keep() -> int:
    try:
        return max(0, int(os.environ.get(LOG_KEEP_ENV, DEFAULT_LOG_KEEP)))
    except ValueError:
        return DEFAULT_LOG_KEEP


def rotate_log(path: Path, keep: int) -> None:
    """build.log → build.log.1 → ... → build.log.<keep>，超出的丢弃。"""
    if keep < 1 or not path.exists():
        return
    oldest = Path(f"{path}.{keep}")
    if oldest.exists():
        oldest.unlink()
    for index in range(keep - 1, 0, -1):
        previous = Path(f"{path}.{index}")
        if previous.exists():
            previous.rename(Path(f"{path}.{index + 1}"))
    path.rename(Path(f"{path}.1"))


# ---------------------------------------------------------------------------
# BuildOutput
# ---------------------------------------------------------------------------

class BuildOutput:
    """统一构建输出管理器。

    由 BuildEngine 创建，注入到 DockerRunner 和各 Builder 中。
    负责：分层输出 → 终端显示 + build.log 双写。
    """

    def __init__(self, target_dir: Path, level: OutputLevel = OutputLevel.NORMAL,
                 *, retry_command: str | None = None):
        self.target_dir = target_dir
        self.level = level
        self.retry_command = retry_command
        self._tty = _is_tty()
        self._lock = threading.Lock()

        # build.log：先轮转再打开，上一次构建的日志不会被当场覆盖
        target_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = target_dir / "build.log"
        rotate_log(self._log_path, _log_keep())
        self._log_file = open(self._log_path, "w", encoding="utf-8")

        # 日志行时间戳：用单调钟算相对耗时。组件级耗时摘要里已经有了，日志
        # 里缺的是**组件内部**哪一步慢 —— rootfs 与 app 各自是一整块，不看
        # 行级时间戳就只知道"rootfs 花了 8 分钟"，不知道花在哪。
        self._log_epoch = time.monotonic()
        self._log_at_line_start = True
        # 头部是这份日志的元数据，不走 _log_write —— 它自己不属于任何一步，
        # 加上 [+0.0s] 只会让"第一条真实记录在哪"变模糊。
        self._log_file.write(
            f"# flange build.log  开始于 "
            f"{time.strftime('%Y-%m-%d %H:%M:%S')}  target={target_dir}\n"
            f"# 行首 [+N.Ns] 是相对构建开始的耗时\n")

        # 构建计时
        self._build_start_time: float = 0.0
        self._phase_start_time: float = 0.0
        self._current_component: str = ""

        # 各组件结果记录（用于摘要）
        self._results: list[dict] = []
        self._failure: BaseException | None = None
        self._ended = False
        self._target = "image"

        # 命令输出缓冲
        self._tail_buffer: deque[str] = deque(maxlen=20)
        self._errors: deque[str] = deque(maxlen=20)
        self._command: tuple[str, ...] = ()

        # 缩进层级：L1(▸)=0, L2(✓)=1
        self._indent: int = 0

        # Spinner 状态
        self._spinner_event: threading.Event | None = None
        self._spinner_thread: threading.Thread | None = None
        self._spinner_label: str = ""

        # 计划顺序只用于导航，不能据此估计耗时百分比或剩余时间。
        self._plan: list[str] = []
        self._done_components: int = 0

        # 只有明确的动作拥有计时状态；普通 status 是即时信息。
        self._step_label: str = ""
        self._step_start: float = 0.0
        self._step_indent: int = 0
        self._last_status = ""
        self._scopes: list[tuple[str, float, int]] = []

        # --- 单行粘性状态 -------------------------------------------------
        # 只在交互终端 + NORMAL 级别启用：QUIET 不该有动画，VERBOSE 下原始
        # 命令输出含 \r 与控制字符，会打乱刷新。
        self._sticky_enabled = (self._tty
                                and level == OutputLevel.NORMAL
                                and supports_color())
        self._sticky_visible = False
        self._sticky_event: threading.Event | None = None
        self._sticky_thread: threading.Thread | None = None

    def close(self):
        """关闭日志文件。"""
        self._spinner_stop_if_running()
        self._sticky_stop()
        # 清理动作不能确认步骤成功；异常路径仍要保留最后一步及其真实状态。
        self._flush_step(success=None, cancelled=isinstance(sys.exception(), KeyboardInterrupt))
        if self._log_file and not self._log_file.closed:
            self._log_file.close()

    # -----------------------------------------------------------------------
    # 内部写入
    # -----------------------------------------------------------------------

    def _write(self, text: str, *, end: str = "\n", flush: bool = False):
        """写入终端 + 日志文件。

        终端侧要先把粘性底栏擦掉再写正文，写完重绘 —— 否则新行会插到底栏
        中间，屏幕从此错乱。日志侧不受影响：底栏是纯终端呈现，从不入日志。
        """
        with self._lock:
            self._erase_sticky()
            sys.stdout.write(text + end)
            self._draw_sticky()
            sys.stdout.flush()
            self._log_write(strip_ansi(text) + end)

    # -----------------------------------------------------------------------
    # 单行粘性状态
    #
    # 只用 CR + EL 原地刷新。多行版本依赖光标上移，但 Docker TTY、窗口缩放
    # 或自动折行都会让物理行数失准，长命令期间每一帧因此变成一条新输出。
    # -----------------------------------------------------------------------

    def _erase_sticky(self) -> None:
        """擦掉状态行并回到行首。调用方须持锁。"""
        if not self._sticky_visible:
            return
        sys.stdout.write("\r\033[K")
        self._sticky_visible = False

    def _draw_sticky(self) -> None:
        """绘制状态行；光标停在行尾。调用方须持锁。"""
        if not self._sticky_enabled:
            return
        line = self._sticky_line()
        if not line:
            return
        sys.stdout.write(line)
        sys.stdout.flush()
        self._sticky_visible = True

    def _sticky_line(self) -> str:
        """只陈述当前工作和已用时间；组件计数不是剩余时间估计。"""
        if not self._current_component and not self._step_label:
            return ""
        width = max(1, min(96, terminal_width()) - 2)
        frame = _SPINNER_FRAMES[int(time.monotonic() * 10) % len(_SPINNER_FRAMES)]
        counter = self._counter_suffix(self._current_component)
        label = " · ".join(part for part in
                           (self._current_component, self._step_label) if part)
        start = self._step_start if self._step_label else self._phase_start_time
        elapsed = format_duration(max(0, time.monotonic() - start)) if start else "0s"
        suffix = f"  已用 {elapsed}"
        prefix = f"  {frame} {counter + ' ' if counter else ''}"
        available = max(1, width - _display_len(prefix + suffix))
        return (self._c(Role.ACTIVE, truncate(prefix + truncate(label, available),
                                             max(1, width - _display_len(suffix))))
                + self._c(Role.MUTED, suffix))

    def _sticky_start(self) -> None:
        """启动底栏刷新线程：计时与 spinner 要动，不能等下一行输出。"""
        if not self._sticky_enabled or self._sticky_thread:
            return
        self._sticky_event = threading.Event()
        self._sticky_thread = threading.Thread(
            target=self._sticky_loop, daemon=True)
        self._sticky_thread.start()

    def _sticky_loop(self) -> None:
        while self._sticky_event and not self._sticky_event.is_set():
            with self._lock:
                self._erase_sticky()
                self._draw_sticky()
            self._sticky_event.wait(0.1)

    def _sticky_stop(self) -> None:
        """停掉刷新线程并擦净底栏 —— 构建结束后不该留残影。

        必须同时**关掉重绘**：`_write` 每写一行都会重画状态，只停线程的话，
        随后的构建摘要会每打一行就重新贴上一条状态行。
        """
        self._sticky_enabled = False
        if self._sticky_event:
            self._sticky_event.set()
        if self._sticky_thread:
            self._sticky_thread.join(timeout=1)
        self._sticky_thread = None
        self._sticky_event = None
        with self._lock:
            self._erase_sticky()
            sys.stdout.flush()

    def _log_write(self, text: str):
        """安全写入日志文件（行首带相对时间戳）。"""
        try:
            if self._log_file and not self._log_file.closed:
                self._log_file.write(self._stamp(strip_ansi(text)))
                self._log_file.flush()
        except OSError:
            pass

    def _stamp(self, text: str) -> str:
        """给每个物理行的行首插入 ``[+N.Ns]``。

        写入不保证以整行为单位（spinner、``end=""`` 的续写都会切开一行），
        所以要跨调用记住"当前是否停在行首"，否则时间戳会插进行中间。
        """
        if not text:
            return text
        prefix = f"[+{time.monotonic() - self._log_epoch:7.1f}s] "
        chunks: list[str] = []
        for line in text.splitlines(keepends=True):
            if self._log_at_line_start:
                chunks.append(prefix)
            chunks.append(line)
            self._log_at_line_start = line.endswith("\n")
        return "".join(chunks)

    def _write_term_only(self, text: str, *, end: str = "", flush: bool = True):
        """仅写终端（用于 spinner \r 刷新）。"""
        with self._lock:
            sys.stdout.write(text + end)
            if flush:
                sys.stdout.flush()

    def _c(self, role: Role, text: str) -> str:
        """按共享语义与当前输出流着色。"""
        if not self._tty:
            return text
        return style(text, role, stream=sys.stdout)

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

    def plan(self, components: list[str]) -> None:
        """注入实际构建顺序，用于当前位置与未执行组件计数。"""
        self._plan = list(components)
        self._done_components = 0

    def build_start(self, target: str, config: dict):
        """以目标和构建范围建立上下文，不占用整屏宽度。"""
        self._build_start_time = time.monotonic()
        self._target = target
        board = config.get("board", "?")
        product = config.get("product", "default")
        variant = config.get("variant", "release")
        title = f"flange build · {board} · {product}-{variant}"
        if self.level != OutputLevel.QUIET:
            self._write("")
            self._field("", title, Role.HEADING)
            self._field("构建", target)
            self._field("日志", str(self._log_path), Role.PATH, preserve=True)
            self._write("")
        else:
            self._log_write(title + "\n")
        self._sticky_start()

    def phase_start(self, component: str):
        """开始组件；源码准备与缓存检查也属于当前阶段。"""
        self._current_component = component
        self._phase_start_time = time.monotonic()
        self._tail_buffer.clear()
        self._errors.clear()
        self._indent = 0
        self._step_label = ""
        self._row(f"▸ {component}", self._counter_suffix(component), Role.HEADING)
        self._indent = 1

    SKIP_REASONS = {"cached": "缓存命中", "disabled": "配置关闭"}

    def phase_skip(self, component: str, reason: str = "cached"):
        """复用与配置关闭分别记录，不让旧阶段残留在实时状态中。"""
        self._spinner_stop_if_running()
        self._flush_step()
        self._current_component = ""
        if component in self._plan:
            self._done_components += 1
        label = self.SKIP_REASONS.get(reason, reason)
        self._indent = 0
        self._row(f"⊘ {component}", label,
                  Role.SUCCESS if reason == "cached" else Role.MUTED)
        self._results.append({"component": component, "status": "skip",
                              "reason": reason, "elapsed": 0.0})

    def phase_end(self, component: str, *, success: bool = True,
                  error: BaseException | None = None):
        """记录组件结果；失败原因由最终摘要统一呈现一次。"""
        cancelled = isinstance(error or sys.exception(), KeyboardInterrupt)
        self._spinner_stop_if_running()
        self._current_component = ""
        self._flush_step(success=success, cancelled=cancelled)
        self._indent = 1
        elapsed = max(0, time.monotonic() - self._phase_start_time)
        self._done_components += 1
        if cancelled:
            mark, label, role = "⚠", "已取消", Role.WARNING
        elif success:
            mark, label, role = "✔", "完成", Role.SUCCESS
        else:
            mark, label, role = "✖", "失败", Role.ERROR
            self._failure = error
        self._row(f"{self._pad}{mark} {label}", format_duration(elapsed), role)
        self._indent = 0
        if self.level != OutputLevel.QUIET:
            self._write("")
        self._results.append({
            "component": component,
            "status": "cancel" if cancelled else ("ok" if success else "fail"),
            "elapsed": elapsed, "error": str(error) if error else None,
        })

    def _row(self, left: str, right: str, left_role: Role,
             right_role: Role = Role.MUTED) -> None:
        """时间列保持紧凑；窄终端折行，日志保存完整原文。"""
        from builder.term import display_width

        plain = left + (f"  {right}" if right else "")
        if self.level == OutputLevel.QUIET:
            self._log_write(plain + "\n")
            return
        width = max(16, min(88, terminal_width() - 2))
        if display_width(left) + display_width(right) + 2 > width:
            for line in wrap(left, width):
                self._write(self._c(left_role, line))
            if right:
                self._write(self._c(right_role, "    " + right))
        else:
            gap = max(2, width - display_width(left) - display_width(right)) if right else 0
            self._write(self._c(left_role, left) + " " * gap
                        + self._c(right_role, right))

    def _field(self, label: str, value: str, role: Role = Role.TEXT,
               *, preserve: bool = False) -> None:
        """字段名与内容分色；路径保持完整以便复制。"""
        prefix = f"  {label}  " if label else ""
        if preserve:
            self._write(self._c(Role.MUTED, prefix) + self._c(role, value))
            return
        width = max(16, min(96, terminal_width()) - _display_len(prefix))
        lines = [line for raw in value.splitlines() or [""] for line in wrap(raw, width)]
        for index, line in enumerate(lines):
            leader = prefix if index == 0 else " " * _display_len(prefix)
            self._write(self._c(Role.MUTED, leader) + self._c(role, line))

    def _counter_suffix(self, component: str) -> str:
        """组件标题右侧的 `[i/N]`；没有计划时留空。"""
        if not self._plan:
            return ""
        try:
            index = self._plan.index(component) + 1
        except ValueError:
            return ""
        return f"[{index}/{len(self._plan)}]"

    # -----------------------------------------------------------------------
    # L2: 状态行
    # -----------------------------------------------------------------------

    def status(self, msg: str):
        """即时信息没有起止契约，不能据此推算耗时或宣称动作成功。"""
        normalized = msg.rstrip(". …")
        self._last_status = normalized
        self._row(f"{self._pad}· {normalized}", "", Role.MUTED)

    @contextmanager
    def step(self, label: str):
        """有明确起止的动作；异常与取消必须留下准确结果。"""
        self.spinner_start(label)
        activity = (self._step_label, self._step_start, self._step_indent)
        self._scopes.append(activity)
        success, cancelled = False, False
        try:
            yield
            success = True
        except BaseException as exc:
            cancelled = isinstance(exc, KeyboardInterrupt)
            raise
        finally:
            self._scopes.pop()
            self._step_label, self._step_start, self._step_indent = activity
            self.spinner_stop(success=success, cancelled=cancelled)

    def _announce_step(self) -> None:
        line = f"{self._pad}· {self._step_label}"
        if self._sticky_enabled or self.level == OutputLevel.QUIET:
            self._log_write(line + "\n")
        else:
            self._row(line, "", Role.ACTIVE)

    def _flush_step(self, *, success: bool | None = True, cancelled: bool = False) -> None:
        """把上一个步骤连同它的耗时落盘。"""
        if not self._step_label:
            return
        elapsed = time.monotonic() - self._step_start
        label, indent = self._step_label, self._step_indent
        self._step_label = ""
        saved, self._indent = self._indent, indent
        # 极短的步骤不显示耗时：多数是纯信息行（"跳过重置与补丁"一类），
        # 给它标个 0.0s 只是噪声。
        duration = format_duration(elapsed) if elapsed >= 0.05 else ""
        if cancelled:
            mark, role = "⚠", Role.WARNING
            label += "（已取消）"
        elif success is False:
            mark, role = "✖", Role.ERROR
        elif success is None:
            mark, role = "·", Role.MUTED
        else:
            mark, role = "✔", Role.SUCCESS
        self._row(f"{self._pad}{mark} {label}", duration, role)
        self._indent = saved

    def warning(self, msg: str):
        """警告：⚠ msg（仅 VERBOSE）"""
        if self.level != OutputLevel.VERBOSE:
            self._log_write(f"{self._pad}⚠ {msg}\n")
            return
        self._write(self._c(Role.WARNING, f"{self._pad}⚠ {msg}"))

    def error(self, msg: str):
        """错误：✗ msg"""
        self._write(self._c(Role.ERROR, f"{self._pad}✗ {msg}"))

    # -----------------------------------------------------------------------
    # L3: 命令输出 (feed_line)
    # -----------------------------------------------------------------------

    def feed_line(self, line: str):
        """原始工具输出全量落盘；所有终端写入共用同一把锁。"""
        line = strip_ansi(line).rstrip("\n")
        with self._lock:
            self._log_write(line + "\n")
            self._tail_buffer.append(line)
            if any(pattern.search(line) for pattern in ERROR_PATTERNS):
                self._errors.append(line)
            if self.level == OutputLevel.VERBOSE:
                self._erase_sticky()
                for part in wrap(line, max(16, terminal_width() - len(self._pad) - 2)):
                    sys.stdout.write(self._c(Role.MUTED, f"{self._pad}│ {part}") + "\n")
                self._draw_sticky()
                sys.stdout.flush()

    def command_start(self, cmd) -> None:
        """建立当前诊断边界，完整日志保留命令以便复现。"""
        with self._lock:
            self._tail_buffer.clear()
            self._errors.clear()
            self._command = tuple(str(value) for value in cmd)
            self._log_write("$ " + shlex.join(self._command) + "\n")

    def command_failed(self, error: BaseException) -> None:
        """将诊断绑定到异常实例；活动缓冲仍可交给下一条清理命令。"""
        with self._lock:
            if not hasattr(error, "_flange_command_diagnostic"):
                error._flange_command_diagnostic = CommandDiagnostic(
                    self._command,
                    tuple(self._errors if self._errors else self._tail_buffer)[-10:],
                )

    def spinner_start(self, label: str):
        """命令使用同一状态行；相邻同名 status 不重复播报。"""
        normalized = label.rstrip(". …")
        if self._scopes and self._step_label == self._scopes[-1][0]:
            # 子命令暂时接管活动行，不能提前宣称父动作完成。
            self._step_label = ""
        if self._step_label != normalized:
            self._flush_step()
            self._step_label = normalized
            self._step_indent = self._indent
            self._step_start = time.monotonic()
            if self._last_status != normalized:
                self._announce_step()
        self._last_status = ""
        self._step_start = time.monotonic()
        self._spinner_pad = self._pad
        if self._sticky_enabled:
            self._sticky_start()
            return
        if not self._tty or not supports_color() or self.level != OutputLevel.NORMAL:
            return
        self._spinner_label = normalized
        self._spinner_event = threading.Event()
        self._spinner_thread = threading.Thread(target=self._spinner_loop, daemon=True)
        self._spinner_thread.start()

    def spinner_stop(self, *, success: bool = True, label: str = "", cancelled: bool = False):
        """命令执行结束，落一行带真实耗时的结果。

        原实现只擦掉 spinner、什么都不留（尽管 docstring 一直写着"替换为
        结果行"），于是最耗时的那条命令在终端上没有任何痕迹。
        """
        self._spinner_stop_if_running()
        self._flush_step(success=success, cancelled=cancelled)
        if self._scopes:
            self._step_label, self._step_start, self._step_indent = self._scopes[-1]

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
        start = time.monotonic()
        pad = self._spinner_pad
        while not self._spinner_event.is_set():
            frame = _SPINNER_FRAMES[idx % len(_SPINNER_FRAMES)]
            elapsed = time.monotonic() - start
            line = f"{pad}{frame} {self._spinner_label}  {elapsed:.0f}s"
            if self._tty:
                colored = self._c(Role.ACTIVE, line)
                with self._lock:
                    sys.stdout.write(f"\r\033[K{colored}")
                    sys.stdout.flush()
            idx += 1
            self._spinner_event.wait(0.08)

    # -----------------------------------------------------------------------
    # 构建摘要
    # -----------------------------------------------------------------------

    def build_end(self, *, success: bool | None = None, cancelled: bool = False,
                  error: BaseException | None = None):
        """一次收尾：结果、相关失败诊断、产物或恢复入口。"""
        if self._ended:
            return
        self._ended = True
        failure = error or self._failure or sys.exception()
        cancelled = (cancelled or isinstance(failure, KeyboardInterrupt)
                     or any(r["status"] == "cancel" for r in self._results))
        has_failure = success is False or any(r["status"] == "fail" for r in self._results)
        self._spinner_stop_if_running()
        self._current_component = ""
        self._flush_step(success=not has_failure, cancelled=cancelled)
        self._sticky_stop()
        elapsed = max(0, time.monotonic() - self._build_start_time) if self._build_start_time else 0
        if cancelled:
            title, role = "⚠ 构建已取消", Role.WARNING
        elif has_failure:
            title, role = "✖ 构建失败", Role.ERROR
        else:
            title, role = "✔ 构建完成", Role.SUCCESS
        self._write(self._c(role, title) + self._c(Role.MUTED, f" · {format_duration(elapsed)}"))
        counts = []
        for status, label in (("ok", "完成"), ("skip", "复用"), ("fail", "失败"), ("cancel", "已取消")):
            count = sum(r["status"] == status and
                        (status != "skip" or r.get("reason", "cached") == "cached")
                        for r in self._results)
            if count:
                counts.append(f"{label} {count}")
        finished = {r["component"] for r in self._results}
        remaining = [name for name in self._plan if name not in finished]
        if remaining:
            counts.append(f"未执行 {len(remaining)}")
        if counts:
            self._field("阶段", " · ".join(counts), Role.MUTED)
        if self.level == OutputLevel.VERBOSE:
            self._write_summary_table(elapsed, min(96, terminal_width()))
        if has_failure and not cancelled:
            failed = next((r for r in self._results if r["status"] == "fail"), None)
            if failed:
                self._field("组件", failed["component"])
            if failure is None and failed and failed.get("error"):
                failure = RuntimeError(failed["error"])
            self._show_error_context(failure)
        if not has_failure and not cancelled:
            self._field("产物", str(self.target_dir), Role.PATH, preserve=True)
        self._field("日志", str(self._log_path), Role.PATH, preserve=True)
        if has_failure or cancelled:
            command = self.retry_command or os.environ.get("FLANGE_BUILD_RETRY_COMMAND")
            if not command:
                command = "flange build" + (f" {self._target}" if self._target != "image" else "")
            self._field("继续" if cancelled else "修复后重试", command, Role.PATH, preserve=True)
        self._write("")
        if failure is not None:
            failure._flange_reported = True
        self.close()

    def _write_summary_table(self, total_elapsed: float, width: int) -> None:
        """详细模式保留组件耗时，不把耗时占比绘制成进度条。"""
        for result in self._results:
            status = {"ok": "完成", "fail": "失败", "skip": "缓存命中",
                      "cancel": "已取消"}[result["status"]]
            if result["status"] == "skip":
                status = self.SKIP_REASONS.get(result.get("reason", "cached"), "跳过")
            text = f"{result['component']} · {status} · {format_duration(result['elapsed'])}"
            self._field("", "  " + text, Role.MUTED)

    def _show_error_context(self, error: BaseException | None = None):
        """只呈现一次原因和当前命令上下文，栈信息保留在完整日志。"""
        if error is not None:
            self._field("原因", str(error), Role.ERROR)
        diagnostic = getattr(error, "_flange_command_diagnostic", None)
        lines = (list(diagnostic.lines) if diagnostic is not None else
                 list(self._errors if self._errors else self._tail_buffer)[-10:])
        # 配置或产物校验失败不应展示上一条成功命令的尾巴。
        if diagnostic is None and isinstance(error, (ValueError, FileNotFoundError)):
            lines = []
        message = str(error) if error is not None else ""
        message_lines = set(message.splitlines())
        seen = set()
        for line in lines:
            if not line.strip() or line in seen or line in message_lines:
                continue
            seen.add(line)
            self._field("│", line, Role.MUTED)
        for note in getattr(error, "__notes__", ()):
            self._field("补充", str(note), Role.MUTED)
        if error is not None:
            self._log_write("".join(traceback.format_exception(error)))
