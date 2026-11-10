"""DockerRunner 命令输出捕获测试。"""

import subprocess
import sys
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from builder.docker import DockerRunner, BuildError
from builder.output import BuildOutput, OutputLevel


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
    @pytest.mark.parametrize("level", [OutputLevel.NORMAL, OutputLevel.VERBOSE])
    def test_宿主构建同样捕获工具双流(self, tmp_path, capsys, monkeypatch, level):
        output = BuildOutput(tmp_path, level=level)
        runner = DockerRunner(tmp_path, output=output)
        runner._in_container = False
        monkeypatch.setattr(runner, "environment_identity", lambda: "sha256:test")
        # 用真实进程代替 Docker 传输，验证宿主路径没有绕开输出通道。
        monkeypatch.setattr(runner, "compose_command", lambda *args: [
            sys.executable, "-c",
            "import sys; print('CC main.o'); print('linker progress', file=sys.stderr)",
        ])
        try:
            runner.run(["make"], env={"PRIVATE_TOKEN": "should-not-be-logged"})
        finally:
            output.close()
        terminal = capsys.readouterr()
        log = (tmp_path / "build.log").read_text()
        assert "CC main.o" in log and "linker progress" in log
        assert ("CC main.o" in terminal.out) is (level == OutputLevel.VERBOSE)
        assert terminal.err == ""
        assert "should-not-be-logged" not in log
        assert "\033" not in terminal.out + log

    def test_环境配置失败保留Compose诊断(self, tmp_path, monkeypatch):
        runner = DockerRunner(tmp_path)
        error = subprocess.CalledProcessError(1, ["docker"], stderr="invalid compose property")
        with patch("subprocess.run", side_effect=error):
            with pytest.raises(BuildError, match="invalid compose property"):
                runner.environment_identity()

    def test_捕获模式保留Docker本身的失败(self, tmp_path, monkeypatch):
        runner = DockerRunner(tmp_path)
        runner._in_container = False
        monkeypatch.setattr(runner, "environment_identity", lambda: "sha256:test")
        result = subprocess.CompletedProcess(["docker"], 1, "", "permission denied")
        with patch("subprocess.run", return_value=result):
            with pytest.raises(BuildError, match="permission denied"):
                runner.run(["make"], capture=True)

    @pytest.mark.parametrize("cancelled", [False, True])
    def test_命令失败或取消不能落为成功(self, output, cancelled):
        class Terminal(StringIO):
            def isatty(self):
                return True

        def command_lines():
            if cancelled:
                raise KeyboardInterrupt
            yield "编译失败\n"

        runner = DockerRunner(output=output)
        proc = MagicMock()
        proc.stdout = command_lines()
        proc.returncode = -15 if cancelled else 2
        output._tty = True
        output._sticky_enabled = False
        stream = Terminal()
        expected = KeyboardInterrupt if cancelled else BuildError
        with patch("sys.stdout", stream), \
             patch.dict("os.environ", {"TERM": "xterm-256color"}, clear=True), \
             patch("subprocess.Popen", return_value=proc), \
             patch.object(output, "_spinner_loop"):
            with pytest.raises(expected):
                runner._run_with_capture(["make"], label="编译内核")
        text = stream.getvalue()
        assert "\033[32m" not in text
        if cancelled:
            assert "\033[33m  ⚠ 编译内核（已取消）" in text
        else:
            assert "\033[1;31m  ✖ 编译内核" in text

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


@pytest.fixture(autouse=True)
def identified_container(monkeypatch):
    """捕获测试模拟由 flange 启动的已标识容器。"""
    monkeypatch.setenv("FLANGE_ENVIRONMENT_PROVIDER", "ubuntu")
    monkeypatch.setenv("FLANGE_BUILD_ENVIRONMENT", "sha256:test-image")
