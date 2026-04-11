"""builder/output.py 单元测试。"""

import time
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from builder.output import (
    BuildOutput,
    OutputLevel,
    strip_ansi,
    _is_tty,
    ERROR_PATTERNS,
    WARNING_PATTERNS,
)


@pytest.fixture
def tmp_target(tmp_path):
    return tmp_path / "target" / "board" / "product" / "variant"


@pytest.fixture
def output_normal(tmp_target):
    out = BuildOutput(tmp_target, level=OutputLevel.NORMAL)
    yield out
    out.close()


@pytest.fixture
def output_verbose(tmp_target):
    out = BuildOutput(tmp_target, level=OutputLevel.VERBOSE)
    yield out
    out.close()


@pytest.fixture
def output_quiet(tmp_target):
    out = BuildOutput(tmp_target, level=OutputLevel.QUIET)
    yield out
    out.close()


# ---------------------------------------------------------------------------
# strip_ansi
# ---------------------------------------------------------------------------

class TestStripAnsi:
    def test_removes_color(self):
        assert strip_ansi("\033[1;34m▸ kernel\033[0m") == "▸ kernel"

    def test_passthrough_plain(self):
        assert strip_ansi("hello world") == "hello world"

    def test_multiple_codes(self):
        text = "\033[0;32m✓\033[0m foo \033[0;90m1.2s\033[0m"
        assert strip_ansi(text) == "✓ foo 1.2s"


# ---------------------------------------------------------------------------
# OutputLevel
# ---------------------------------------------------------------------------

class TestOutputLevel:
    def test_enum_values(self):
        assert OutputLevel.QUIET.value == "quiet"
        assert OutputLevel.NORMAL.value == "normal"
        assert OutputLevel.VERBOSE.value == "verbose"


# ---------------------------------------------------------------------------
# BuildOutput 初始化
# ---------------------------------------------------------------------------

class TestBuildOutputInit:
    def test_creates_log_file(self, tmp_target):
        out = BuildOutput(tmp_target, level=OutputLevel.NORMAL)
        assert (tmp_target / "build.log").exists()
        out.close()

    def test_creates_target_dir(self, tmp_target):
        out = BuildOutput(tmp_target, level=OutputLevel.NORMAL)
        assert tmp_target.exists()
        out.close()

    def test_default_level(self, tmp_target):
        out = BuildOutput(tmp_target)
        assert out.level == OutputLevel.NORMAL
        out.close()


# ---------------------------------------------------------------------------
# L1 阶段标题
# ---------------------------------------------------------------------------

class TestPhase:
    def test_phase_skip_records_result(self, output_normal):
        output_normal.phase_skip("bootloader")
        assert len(output_normal._results) == 1
        assert output_normal._results[0]["status"] == "skip"
        assert output_normal._results[0]["component"] == "bootloader"

    def test_phase_start_clears_buffers(self, output_normal):
        output_normal._tail_buffer.append("old line")
        output_normal._errors.append("old error")
        output_normal.phase_start("kernel")
        assert len(output_normal._tail_buffer) == 0
        assert len(output_normal._errors) == 0

    def test_phase_end_success(self, output_normal):
        output_normal.phase_start("kernel")
        time.sleep(0.01)
        output_normal.phase_end("kernel", success=True)
        assert len(output_normal._results) == 1
        assert output_normal._results[0]["status"] == "ok"
        assert output_normal._results[0]["elapsed"] > 0

    def test_phase_end_failure(self, output_normal):
        output_normal.phase_start("kernel")
        output_normal.phase_end("kernel", success=False,
                                error=Exception("编译错误"))
        assert output_normal._results[0]["status"] == "fail"
        assert "编译错误" in output_normal._results[0]["error"]


# ---------------------------------------------------------------------------
# L2 状态行
# ---------------------------------------------------------------------------

class TestStatusLines:
    def test_status_writes_to_log(self, output_normal, tmp_target):
        output_normal.status("源码就绪")
        output_normal.close()
        log_content = (tmp_target / "build.log").read_text()
        assert "源码就绪" in log_content

    def test_warning_only_in_verbose(self, output_normal, tmp_target):
        """NORMAL 模式 warning 只写日志，不写终端。"""
        buf = StringIO()
        with patch("sys.stdout", buf):
            output_normal.warning("一个警告")
        # 终端不应有警告
        assert "警告" not in buf.getvalue()
        # 日志应有
        output_normal.close()
        log_content = (tmp_target / "build.log").read_text()
        assert "警告" in log_content

    def test_warning_in_verbose(self, output_verbose):
        """VERBOSE 模式 warning 写终端。"""
        buf = StringIO()
        with patch("sys.stdout", buf):
            output_verbose.warning("一个警告")
        assert "警告" in buf.getvalue()

    def test_status_quiet_suppressed(self, output_quiet):
        """QUIET 模式 status 不显示。"""
        buf = StringIO()
        with patch("sys.stdout", buf):
            output_quiet.status("被抑制的信息")
        assert buf.getvalue() == ""


# ---------------------------------------------------------------------------
# feed_line
# ---------------------------------------------------------------------------

class TestFeedLine:
    def test_writes_to_log(self, output_normal, tmp_target):
        output_normal.feed_line("CC init/main.o")
        output_normal.close()
        log_content = (tmp_target / "build.log").read_text()
        assert "CC init/main.o" in log_content

    def test_tail_buffer(self, output_normal):
        for i in range(30):
            output_normal.feed_line(f"line {i}")
        assert len(output_normal._tail_buffer) == 20
        assert output_normal._tail_buffer[0] == "line 10"
        assert output_normal._tail_buffer[-1] == "line 29"

    def test_error_detection(self, output_normal):
        output_normal.feed_line("drivers/gpu/foo.c:42: error: undefined symbol")
        assert len(output_normal._errors) == 1
        assert "error:" in output_normal._errors[0]

    def test_make_error_detection(self, output_normal):
        output_normal.feed_line("make[3]: *** [Makefile:123: foo.o] Error 1")
        assert len(output_normal._errors) == 1

    def test_no_false_positive(self, output_normal):
        output_normal.feed_line("CC drivers/net/ethernet.o")
        assert len(output_normal._errors) == 0

    def test_verbose_prints_to_stdout(self, output_verbose):
        buf = StringIO()
        with patch("sys.stdout", buf):
            output_verbose.feed_line("CC init/main.o")
        assert "CC init/main.o" in buf.getvalue()

    def test_normal_no_stdout(self, output_normal):
        buf = StringIO()
        with patch("sys.stdout", buf):
            output_normal.feed_line("CC init/main.o")
        assert "CC init/main.o" not in buf.getvalue()


# ---------------------------------------------------------------------------
# 错误模式
# ---------------------------------------------------------------------------

class TestErrorPatterns:
    @pytest.mark.parametrize("line", [
        "foo.c:10: error: expected ';'",
        "make[2]: *** [Makefile:42: all] Error 2",
        "undefined reference to `main'",
        "E: Unable to locate package foo",
        "dpkg: error processing package foo",
        "fatal: not a git repository",
    ])
    def test_error_patterns_match(self, line):
        assert any(p.search(line) for p in ERROR_PATTERNS)

    @pytest.mark.parametrize("line", [
        "CC drivers/net/ethernet.o",
        "  INSTALL lib/modules/5.10.0/kernel/foo.ko",
        "Hit:1 http://archive.ubuntu.com/ubuntu noble InRelease",
    ])
    def test_no_false_positive(self, line):
        assert not any(p.search(line) for p in ERROR_PATTERNS)

    @pytest.mark.parametrize("line", [
        "foo.c:10: warning: unused variable",
        "W: GPG error: http://archive.ubuntu.com",
    ])
    def test_warning_patterns_match(self, line):
        assert any(p.search(line) for p in WARNING_PATTERNS)


# ---------------------------------------------------------------------------
# 错误上下文
# ---------------------------------------------------------------------------

class TestErrorContext:
    def test_show_errors_from_list(self, output_normal):
        output_normal._errors = ["foo.c:10: error: bad", "make[1]: *** Error"]
        buf = StringIO()
        with patch("sys.stdout", buf):
            output_normal._show_error_context()
        output_text = strip_ansi(buf.getvalue())
        assert "foo.c:10: error: bad" in output_text
        assert "┄" in output_text

    def test_fallback_to_tail(self, output_normal):
        for i in range(5):
            output_normal._tail_buffer.append(f"tail line {i}")
        buf = StringIO()
        with patch("sys.stdout", buf):
            output_normal._show_error_context()
        output_text = strip_ansi(buf.getvalue())
        assert "tail line 4" in output_text


# ---------------------------------------------------------------------------
# 构建摘要
# ---------------------------------------------------------------------------

class TestBuildSummary:
    def test_summary_contains_components(self, output_normal):
        output_normal._build_start_time = time.time() - 10
        output_normal._results = [
            {"component": "kernel", "status": "ok", "elapsed": 8.0},
            {"component": "bootloader", "status": "skip", "elapsed": 0.1},
        ]
        buf = StringIO()
        with patch("sys.stdout", buf):
            output_normal.build_end()
        text = strip_ansi(buf.getvalue())
        assert "kernel" in text
        assert "bootloader" in text
        assert "构建完成" in text
        assert "build.log" in text

    def test_summary_failure(self, output_normal):
        output_normal._build_start_time = time.time() - 5
        output_normal._results = [
            {"component": "kernel", "status": "fail", "elapsed": 4.0,
             "error": "编译错误"},
        ]
        buf = StringIO()
        with patch("sys.stdout", buf):
            output_normal.build_end()
        text = strip_ansi(buf.getvalue())
        assert "构建失败" in text
        assert "kernel" in text


# ---------------------------------------------------------------------------
# 非 TTY 模式
# ---------------------------------------------------------------------------

class TestNonTTY:
    def test_no_ansi_when_not_tty(self, tmp_target):
        out = BuildOutput(tmp_target, level=OutputLevel.NORMAL)
        out._tty = False
        colored = out._c("\033[1;34m", "hello")
        assert colored == "hello"
        out.close()

    def test_spinner_skipped_when_not_tty(self, tmp_target):
        out = BuildOutput(tmp_target, level=OutputLevel.NORMAL)
        out._tty = False
        out.spinner_start("编译中...")
        # 无 spinner 线程启动
        assert out._spinner_thread is None
        out.close()
