"""统一构建输出模块 — 分层结构化输出、Spinner、日志持久化。"""

import os
import re
import shutil
import sys
import time
import threading
import traceback
from collections import deque
from enum import Enum
from pathlib import Path

from builder.term import (
    duration_bar,
    format_duration,
    pad,
    progress_bar,
    rpad,
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

    def __init__(self, target_dir: Path, level: OutputLevel = OutputLevel.NORMAL):
        self.target_dir = target_dir
        self.level = level
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

        # 命令输出缓冲
        self._tail_buffer: deque[str] = deque(maxlen=20)
        self._errors: list[str] = []

        # 缩进层级：L1(▸)=0, L2(✓)=1
        self._indent: int = 0

        # Spinner 状态
        self._spinner_event: threading.Event | None = None
        self._spinner_thread: threading.Thread | None = None
        self._spinner_label: str = ""

        # --- 进度模型 -----------------------------------------------------
        # 构建开始前由 engine 注入完整组件序列（拓扑序已知），底栏据此显示
        # [i/N] 与总进度。没有它就只能显示"正在做某件事"，用户无从判断还要
        # 等多久 —— 而全量构建要跑 50 分钟。
        self._plan: list[str] = []
        self._done_components: int = 0

        # --- 当前步骤 -----------------------------------------------------
        # 步骤耗时不改调用方（仓库里 126 处 _status），改为自动测量：一个
        # 步骤的耗时 = 从它开始到下一个步骤开始。因此行要**延后**到步骤结束
        # 才落盘，进行中的那一步显示在底栏上并带实时计时。
        self._step_label: str = ""
        self._step_start: float = 0.0
        self._step_indent: int = 0

        # --- 粘性底栏 -----------------------------------------------------
        # 只在交互终端 + NORMAL 级别启用：QUIET 不该有动画，VERBOSE 下原始
        # 命令输出含 \r 与控制字符，会打乱行数记账。
        self._sticky_enabled = (self._tty
                                and level == OutputLevel.NORMAL
                                and supports_color())
        self._sticky_rows: int = 0
        self._sticky_event: threading.Event | None = None
        self._sticky_thread: threading.Thread | None = None

    def close(self):
        """关闭日志文件。"""
        self._flush_step()  # 异常路径下仍要把最后一步落盘，否则它永远不出现
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
            if flush:
                sys.stdout.flush()
            self._log_write(strip_ansi(text) + end)

    # -----------------------------------------------------------------------
    # 粘性底栏
    #
    # 做法是"擦掉重画"而不是用 DECSTBM 滚动区：滚动区在窗口缩放、tmux
    # 分屏、以及构建结束后恢复不干净时会留下卡住的区域，而擦掉重画最坏
    # 情况只是闪一下。
    # -----------------------------------------------------------------------

    def _erase_sticky(self) -> None:
        """擦掉底栏，光标回到底栏第一行的行首。调用方须持锁。"""
        if not self._sticky_rows:
            return
        if self._sticky_rows > 1:
            sys.stdout.write(f"\033[{self._sticky_rows - 1}A")
        sys.stdout.write("\r\033[J")
        self._sticky_rows = 0

    def _draw_sticky(self) -> None:
        """绘制底栏；光标停在最后一行行尾。调用方须持锁。"""
        if not self._sticky_enabled:
            return
        lines = self._sticky_lines()
        if not lines:
            return
        sys.stdout.write("\n".join(lines))
        sys.stdout.flush()
        self._sticky_rows = len(lines)

    def _sticky_lines(self) -> list[str]:
        """底栏内容：当前步骤 + 总进度。"""
        if not self._plan or not self._current_component:
            return []
        width = terminal_width()

        # 第一行：正在做什么，带实时计时
        frame = _SPINNER_FRAMES[int(time.time() * 12) % len(_SPINNER_FRAMES)]
        if self._step_label:
            elapsed = format_duration(time.time() - self._step_start)
            right = f"{frame} {elapsed}"
            left = f" ▸ {self._current_component}  ·  {self._step_label}"
        else:
            right = frame
            left = f" ▸ {self._current_component}"
        gap = max(1, width - len(right) - _display_len(left))
        first = self._c(_Colors.BLUE_BOLD, truncate(left, width - len(right) - 1)) \
            + " " * gap + self._c(_Colors.GRAY, right)

        # 第二行：整体进度
        total = len(self._plan)
        done = min(self._done_components, total)
        counter = f" [{done}/{total}]"
        total_elapsed = format_duration(time.time() - self._build_start_time) \
            if self._build_start_time else ""
        tail = f"{done * 100 // total:>3}%   总计 {total_elapsed}"
        bar_width = max(8, width - len(counter) - len(tail) - 4)
        second = (self._c(_Colors.WHITE, counter) + " "
                  + self._c(_Colors.GREEN, progress_bar(done / total, bar_width))
                  + "  " + self._c(_Colors.GRAY, tail))
        return [first, second]

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

        必须同时**关掉重绘**：`_write` 每写一行都会重画底栏，只停线程的话，
        随后的构建摘要会每打一行就被重新贴上一条底栏，最后屏幕上还留着一条
        写着 100% 的进度条。
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
                self._log_file.write(self._stamp(text))
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

    def plan(self, components: list[str]) -> None:
        """注入本次构建的完整组件序列。

        `_topo_sort` 在进入循环前就算出了拓扑序，把它交给输出层，底栏才能
        显示 `[i/N]` 与总进度。没有它只能显示"正在做某件事"——而全量构建
        要跑近一小时，用户无从判断还要等多久。
        """
        self._plan = list(components)
        self._done_components = 0

    def build_start(self, target: str, config: dict):
        """打印构建横幅。"""
        self._build_start_time = time.time()
        board = config.get("board", "?")
        product = config.get("product", "default")
        variant = config.get("variant", "release")
        width = terminal_width()
        title = f"flange build · {board} · {product}-{variant}"
        self._write("")
        self._write(self._c(_Colors.WHITE, "═" * width))
        self._write(self._c(_Colors.BLUE_BOLD, f" {title}")
                    + self._c(_Colors.GRAY,
                              rpad(f"目标 {target} ", width - len(title) - 1)))
        self._write(self._c(_Colors.WHITE, "═" * width))
        self._write("")
        self._sticky_start()

    def phase_start(self, component: str):
        """开始一个组件阶段：▸ component"""
        self._current_component = component
        self._phase_start_time = time.time()
        self._tail_buffer.clear()
        self._errors.clear()
        self._indent = 0
        # [i/N] 右对齐，与下方步骤行的耗时列、跳过行的状态列共用同一条右边界
        self._row(f"▸ {component}", self._counter_suffix(component),
                  _Colors.BLUE_BOLD)
        self._indent = 1
        self._step_label = ""

    #: 跳过原因 → 展示文案。"缓存命中"与"配置关闭"是两件事：前者说明产物
    #: 已经就绪，后者说明这个组件根本不参与本次构建（recovery/amp 的开关）。
    #: 原实现两者共用一条"无变更，跳过"，会让人以为关掉的组件有陈旧产物。
    SKIP_REASONS = {"cached": "缓存命中", "disabled": "配置关闭"}

    def phase_skip(self, component: str, reason: str = "cached"):
        """组件跳过：⊘ 一整行。

        跳过是一整行而不是两行 —— 跳过的组件通常占多数，每个占两行会把真正
        在构建的那个挤出屏幕。
        """
        elapsed = 0.1
        self._done_components += 1
        label = self.SKIP_REASONS.get(reason, reason)
        self._indent = 0
        self._row(f"⊘ {component}",
                  f"{label}   {rpad(format_duration(elapsed), 7)}",
                  _Colors.GRAY)
        self._results.append({
            "component": component,
            "status": "skip",
            "reason": reason,
            "elapsed": elapsed,
        })

    def phase_end(self, component: str, *, success: bool = True,
                  error: Exception | None = None):
        """结束组件阶段。"""
        self._spinner_stop_if_running()
        self._flush_step()
        self._indent = 1
        elapsed = time.time() - self._phase_start_time
        self._done_components += 1
        if success:
            self._row(f"{self._pad}✔ 完成", format_duration(elapsed),
                      _Colors.GREEN)
        else:
            self._row(f"{self._pad}✖ 失败", format_duration(elapsed),
                      _Colors.RED_BOLD, _Colors.RED_BOLD)
            self._show_error_context(error)
        self._indent = 0
        self._write("")
        self._results.append({
            "component": component,
            "status": "ok" if success else "fail",
            "elapsed": elapsed,
            "error": str(error) if error else None,
        })

    def _row(self, left: str, right: str, left_color: str,
             right_color: str = _Colors.GRAY) -> None:
        """左文右值的一行，右值贴齐终端右边。

        耗时散落在文本末尾（`✔ 安装内核模块  0.4s`）时，眼睛要在锯齿状的
        位置间来回找；对齐成列之后"哪一步慢"扫一眼就出来了。
        """
        from builder.term import display_width

        width = terminal_width()
        right_width = display_width(right)
        left = truncate(left, max(0, width - right_width - 2))
        gap = max(1, width - display_width(left) - right_width)
        self._write(self._c(left_color, left) + " " * gap
                    + self._c(right_color, right))

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
        """一个步骤开始。

        耗时**自动测量**：一个步骤的耗时 = 从它开始到下一个步骤开始。仓库里
        有 126 处 `_status` 调用，要求每处都显式声明起止不现实，而"这一步花
        了多久"恰恰是终端上最缺的信息 —— 组件级耗时摘要里有，组件内部没有，
        于是 rootfs 那 82 秒花在哪只能去翻日志。

        代价是行要延后到步骤结束才落盘。交互终端上进行中的那一步显示在粘性
        底栏并带实时计时，所以不会觉得"卡住了没反应"。

        非交互环境（CI、管道）同样延后：那里本就没有"实时感"可言，而事后翻
        日志找"时间花在哪"恰恰是最主要的用途 —— 立即打印一行没有耗时的
        `· 步骤名`，等于把这个信息永久丢掉。两边落盘的行因此形状一致。
        """
        if self.level == OutputLevel.QUIET:
            return
        self._flush_step()
        # 收掉尾部省略号：`安装内核模块...` 是"进行中"的措辞，而这一行现在
        # 是以完成态 ✔ 呈现的。同时让它与 docker 命令标签可比，两者同名时
        # 合成一步。
        self._step_label = msg.rstrip(". ")
        self._step_start = time.time()
        self._step_indent = self._indent

    def _flush_step(self) -> None:
        """把上一个步骤连同它的耗时落盘。"""
        if not self._step_label:
            return
        elapsed = time.time() - self._step_start
        label, indent = self._step_label, self._step_indent
        self._step_label = ""
        saved, self._indent = self._indent, indent
        # 极短的步骤不显示耗时：多数是纯信息行（"跳过重置与补丁"一类），
        # 给它标个 0.0s 只是噪声。
        duration = format_duration(elapsed) if elapsed >= 0.05 else ""
        self._row(f"{self._pad}✔ {label}", duration, _Colors.GREEN)
        self._indent = saved

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
        """一条外部命令开始执行。

        命令自成一步：它有明确的起止（Popen 到 wait），耗时可以精确归属。

        这一点很重要 —— 步骤耗时是"到下一次 status 为止"的近似，而真正耗时
        的往往是紧随其后的那条命令（编译内核、apt install）。不给命令单独
        计时，那 2 分钟就会被算到上一行状态头上，实测出现过
        `✔ flange_overrides.config 生成  2m14s` 这种**误导性**的归属 ——
        它读起来像是生成一个 config 文件花了两分钟。
        """
        normalized = label.rstrip(". ")
        # builder 常常先 _status("编译 X...") 再 docker.run(label="编译 X...")，
        # 同一件事说两遍。前者耗时必然接近零，落成两行（其中一行还没有耗时）
        # 纯属噪声 —— 视为同一步，直接接管计时。
        if (self._step_label == normalized
                and time.time() - self._step_start < 0.05):
            self._step_label = ""
        self._flush_step()
        self._step_label = normalized
        self._step_start = time.time()
        self._step_indent = self._indent
        self._spinner_pad = self._pad  # 固定 spinner 启动时的缩进
        if self._sticky_enabled:
            return  # 底栏已经在显示当前步骤与实时计时，无需再起一个 spinner
        if not self._tty or self.level == OutputLevel.QUIET:
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
        """命令执行结束，落一行带真实耗时的结果。

        原实现只擦掉 spinner、什么都不留（尽管 docstring 一直写着"替换为
        结果行"），于是最耗时的那条命令在终端上没有任何痕迹。
        """
        self._spinner_stop_if_running()
        self._flush_step()

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
        self._flush_step()
        self._sticky_stop()
        total_elapsed = time.time() - self._build_start_time
        has_failure = any(r["status"] == "fail" for r in self._results)
        width = terminal_width()

        self._write(self._c(_Colors.WHITE, "─" * width))
        if has_failure:
            self._write(self._c(_Colors.RED_BOLD, " ✖ 构建失败")
                        + self._fmt_time_right(total_elapsed, prefix="耗时"))
        else:
            self._write(self._c(_Colors.GREEN, " ✔ 构建完成")
                        + self._fmt_time_right(total_elapsed, prefix="总耗时"))
        self._write(self._c(_Colors.WHITE, "─" * width))
        self._write_summary_table(total_elapsed, width)
        self._write(self._c(_Colors.WHITE, "─" * width))
        self._write(self._c(_Colors.GRAY, f"  日志  {self._log_path}"))
        self._write("")

        self.close()

    def _write_summary_table(self, total_elapsed: float, width: int) -> None:
        """组件耗时表。

        列宽按最长组件名算，不写死 —— 原实现固定 12 列，`device-tree-overlay`
        有 19 个字符，把状态列直接挤没了（`device-tree-overlay跳过`）。

        右侧的条是**耗时占比**不是进度，所以用与进度条不同的字形，并且给出
        列名。原实现用 █/░ 画占比，与进度条同形，会被读成"这个组件只完成了
        59%"。
        """
        if not self._results:
            return
        name_width = max(12, max(len(r["component"]) for r in self._results))
        bar_width = max(10, min(24, width - name_width - 34))

        self._write(self._c(_Colors.GRAY,
                            f"  {pad('组件', name_width + 2)}"
                            f"{pad('状态', 10)}{rpad('耗时', 8)}   耗时占比"))

        slowest = max((r["elapsed"] for r in self._results
                       if r["status"] == "ok"), default=0)
        for result in self._results:
            self._write(self._summary_row(
                result, total_elapsed, slowest, name_width, bar_width))

    def _summary_row(self, result: dict, total_elapsed: float, slowest: float,
                     name_width: int, bar_width: int) -> str:
        name = pad(result["component"], name_width + 2)
        elapsed = result["elapsed"]
        duration = rpad(format_duration(elapsed), 8)
        status = result["status"]

        if status == "skip":
            label = self.SKIP_REASONS.get(result.get("reason", "cached"), "跳过")
            return self._c(_Colors.GRAY, f"  {name}{pad(label, 10)}{duration}")
        if status == "fail":
            row = (self._c(_Colors.RED_BOLD, f"  {name}")
                   + self._c(_Colors.RED_BOLD, pad("失败", 10))
                   + self._c(_Colors.RED_BOLD, duration))
            if result.get("error"):
                row += self._c(_Colors.RED, f"   {self._brief(result['error'])}")
            return row

        share = elapsed / total_elapsed if total_elapsed > 0 else 0
        bar = duration_bar(share, bar_width)
        # 最慢的那个高亮：摘要的用处就是回答"时间花在哪"
        bar_color = _Colors.YELLOW if elapsed >= slowest > 0 else _Colors.GRAY
        return (f"  {name}{pad('构建', 10)}{duration}"
                + f"   {self._c(bar_color, bar)}"
                + self._c(_Colors.GRAY, f" {share:>4.0%}"))

    # -----------------------------------------------------------------------
    # 错误上下文
    # -----------------------------------------------------------------------

    def _show_error_context(self, error: Exception | None = None):
        """显示失败诊断：异常原文 + 命令输出上下文 + 日志指针。

        之前这里只打命令输出的尾巴，抛出的异常本身从不出现在任何地方 ——
        engine 捕获后只把 ``str(error)`` 存进摘要，而摘要按 40 字符硬截断。
        结果是"参数校验失败"这类由 flange 自己抛出、命令输出里根本没有对应
        行的错误，用户在终端上看不到任何原因。
        """
        pad = self._pad
        border = self._c(_Colors.RED,
                         f"{pad}" + "┄" * max(20, terminal_width() - len(pad) - 2))
        lines = (self._errors if self._errors else list(self._tail_buffer))[-15:]
        if not lines and error is None:
            return

        self._write(border)
        if error is not None:
            # 异常原文不截断 —— 它是定位问题最关键的一句。超宽时折行，
            # 而不是让终端在任意位置自己折、把缩进对齐打乱。
            body_width = max(20, terminal_width() - len(pad))
            for raw_line in f"{type(error).__name__}: {error}".splitlines():
                for line in wrap(raw_line, body_width):
                    self._write(self._c(_Colors.RED_BOLD, f"{pad}{line}"))
            if lines:
                self._write(self._c(_Colors.RED, f"{pad}"))
        for line in lines:
            self._write(self._c(_Colors.RED, f"{pad}{line}"))
        self._write(border)
        self._write(self._c(_Colors.GRAY, f"{pad}完整日志: {self._log_path}"))
        # traceback 只进日志：终端要的是结论，排查的人要的是栈。
        if error is not None and error.__traceback__ is not None:
            self._log_write("".join(traceback.format_exception(error)))

    # -----------------------------------------------------------------------
    # 工具
    # -----------------------------------------------------------------------

    def _brief(self, message: str) -> str:
        """摘要行里的一行式错误。

        取首行而不是前 40 个字符：多行异常的第一行才是结论，按字符截断经常
        正好切在"Traceback"或路径中间。宽度跟随终端，窄终端才截断，且用 …
        明示被截过，配合上面 `_show_error_context` 打出的原文与日志路径。
        """
        first = message.strip().splitlines()[0] if message.strip() else ""
        # 按显示宽度截断：中文占两列，按字符数截会让这一行溢出到下一行，
        # 摘要表的对齐当场垮掉。
        return truncate(first, max(30, terminal_width() - 44))

    def _fmt_time_right(self, seconds: float, *, prefix: str = "") -> str:
        """格式化耗时（右侧灰色）。

        走 `format_duration`：2338.4s 要用户自己心算成 39 分钟，而摘要里最该
        一眼看懂的就是"哪一步花了最久"。
        """
        label = f"{prefix} " if prefix else ""
        return self._c(_Colors.GRAY, f"  {label}{format_duration(seconds)}")
