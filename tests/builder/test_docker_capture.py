"""DockerRunner 命令输出捕获测试。"""

import subprocess
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from builder.docker import DockerRunner, BuildError
from builder.output import BuildOutput, OutputLevel, strip_ansi


@pytest.fixture
def tmp_target(tmp_path):
    return tmp_path / "target"


@pytest.fixture
def output(tmp_target):
    out = BuildOutput(tmp_target, level=OutputLevel.NORMAL)
    out._tty = False  # 测试中禁用 TTY
    yield out
    out.close()


@pytest.fixture
def output_verbose(tmp_target):
    out = BuildOutput(tmp_target, level=OutputLevel.VERBOSE)
    out._tty = False
    yield out
    out.close()


# ---------------------------------------------------------------------------
# DockerRunner + output 注入
# ---------------------------------------------------------------------------

class TestDockerRunnerCapture:
    def test_output_injected(self, output):
        runner = DockerRunner(output=output)
        assert runner.output is output

    def test_no_output_passthrough(self):
        """无 output 时保持原行为。"""
        runner = DockerRunner()
        assert runner.output is None

    @patch("builder.docker._is_inside_container", return_value=True)
    def test_capture_mode_feeds_lines(self, mock_container, output, tmp_target):
        """Popen 捕获模式将输出 feed 到 BuildOutput。"""
        runner = DockerRunner(output=output)

        # mock Popen
        mock_proc = MagicMock()
        mock_proc.stdout = iter(["line 1\n", "line 2\n", "done\n"])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0

        with patch("subprocess.Popen", return_value=mock_proc):
            runner.run(["echo", "hello"])

        # 验证 feed_line 被调用（通过 tail_buffer 检查）
        assert "line 1" in list(output._tail_buffer)
        assert "done" in list(output._tail_buffer)

    @patch("builder.docker._is_inside_container", return_value=True)
    def test_capture_mode_logs_to_file(self, mock_container, output, tmp_target):
        """捕获的输出写入 build.log。"""
        runner = DockerRunner(output=output)

        mock_proc = MagicMock()
        mock_proc.stdout = iter(["CC main.o\n", "LD vmlinux\n"])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0

        with patch("subprocess.Popen", return_value=mock_proc):
            runner.run(["make"])

        output.close()
        log_content = (tmp_target / "build.log").read_text()
        assert "CC main.o" in log_content
        assert "LD vmlinux" in log_content

    @patch("builder.docker._is_inside_container", return_value=True)
    def test_capture_mode_detects_errors(self, mock_container, output):
        """捕获模式检测错误行。"""
        runner = DockerRunner(output=output)

        mock_proc = MagicMock()
        mock_proc.stdout = iter([
            "CC foo.o\n",
            "foo.c:10: error: bad thing\n",
            "make[1]: *** Error 1\n",
        ])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 2

        with patch("subprocess.Popen", return_value=mock_proc):
            with pytest.raises(BuildError):
                runner.run(["make"])

        assert len(output._errors) == 2

    @patch("builder.docker._is_inside_container", return_value=True)
    def test_capture_bypassed_for_capture_flag(self, mock_container, output):
        """capture=True 时不走 Popen 捕获（需返回 stdout）。"""
        runner = DockerRunner(output=output)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["echo"], returncode=0, stdout="hello", stderr="")
            result = runner.run(["echo", "hello"], capture=True)

        assert mock_run.called
        assert result.stdout == "hello"

    @patch("builder.docker._is_inside_container", return_value=True)
    def test_spinner_started_with_label(self, mock_container, output):
        """传递 label 时启动 spinner。"""
        runner = DockerRunner(output=output)

        mock_proc = MagicMock()
        mock_proc.stdout = iter(["ok\n"])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0

        with patch("subprocess.Popen", return_value=mock_proc):
            with patch.object(output, "spinner_start") as mock_start, \
                 patch.object(output, "spinner_stop") as mock_stop:
                runner.run(["make"], label="编译中...")

        mock_start.assert_called_once_with("编译中...")
        mock_stop.assert_called_once()


# ---------------------------------------------------------------------------
# feed_line 详细测试
# ---------------------------------------------------------------------------

class TestFeedLineIntegration:
    def test_verbose_prints_prefixed(self, output_verbose):
        """VERBOSE 模式输出带 │ 前缀。"""
        buf = StringIO()
        with patch("sys.stdout", buf):
            output_verbose.feed_line("CC init/main.o\n")
        assert "│" in buf.getvalue()
        assert "CC init/main.o" in buf.getvalue()

    def test_normal_no_stdout_for_regular_lines(self, output):
        """NORMAL 模式不打印普通行到 stdout。"""
        buf = StringIO()
        with patch("sys.stdout", buf):
            output.feed_line("CC init/main.o\n")
        assert "CC init/main.o" not in buf.getvalue()

    def test_tail_buffer_rolling(self, output):
        """tail_buffer 只保留最后 20 行。"""
        for i in range(30):
            output.feed_line(f"line {i}\n")
        assert len(output._tail_buffer) == 20
        assert output._tail_buffer[0] == "line 10"

    def test_apt_error_detected(self, output):
        output.feed_line("E: Unable to locate package nonexistent\n")
        assert len(output._errors) == 1

    def test_git_fatal_detected(self, output):
        output.feed_line("fatal: not a git repository\n")
        assert len(output._errors) == 1
