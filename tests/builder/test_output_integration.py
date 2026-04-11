"""构建输出系统集成测试。"""

import subprocess
import time
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from builder.output import BuildOutput, OutputLevel, strip_ansi
from builder.docker import DockerRunner, BuildError


@pytest.fixture
def tmp_target(tmp_path):
    return tmp_path / "target" / "board" / "product" / "variant"


# ---------------------------------------------------------------------------
# 7.1 完整 build 流程模拟
# ---------------------------------------------------------------------------

class TestBuildFlowIntegration:
    """模拟完整 build 流程，验证输出结构。"""

    def test_full_build_output_structure(self, tmp_target):
        """模拟多组件构建，验证 phase/summary 输出。"""
        out = BuildOutput(tmp_target, level=OutputLevel.NORMAL)
        out._tty = False

        buf = StringIO()
        config = {"board": "tspi-rk3566", "product": "default", "variant": "debug"}

        with patch("sys.stdout", buf):
            out.build_start("image", config)

            # 组件 1: 跳过
            out.phase_skip("app")

            # 组件 2: 成功
            out.phase_start("kernel")
            out.status("源码就绪")
            out.status("补丁应用 (2 patches)")
            time.sleep(0.01)
            out.phase_end("kernel", success=True)

            # 组件 3: 成功
            out.phase_start("rootfs")
            out.status("Phase 1: base 缓存命中")
            time.sleep(0.01)
            out.phase_end("rootfs", success=True)

            out.build_end()

        text = strip_ansi(buf.getvalue())

        # 横幅
        assert "flange build" in text
        assert "tspi-rk3566" in text

        # 组件阶段
        assert "▸ app" in text
        assert "⊘" in text
        assert "▸ kernel" in text
        assert "源码就绪" in text
        assert "▸ rootfs" in text

        # 摘要
        assert "构建完成" in text
        assert "kernel" in text
        assert "build.log" in text

    def test_build_log_created(self, tmp_target):
        """验证 build.log 文件生成且包含全量输出。"""
        out = BuildOutput(tmp_target, level=OutputLevel.NORMAL)
        out._tty = False
        config = {"board": "test", "product": "p", "variant": "v"}

        with patch("sys.stdout", StringIO()):
            out.build_start("image", config)
            out.phase_start("kernel")
            out.status("源码就绪")
            out.feed_line("CC init/main.o\n")
            out.feed_line("LD vmlinux\n")
            out.phase_end("kernel", success=True)
            out.build_end()

        log_path = tmp_target / "build.log"
        assert log_path.exists()
        content = log_path.read_text()
        assert "CC init/main.o" in content
        assert "LD vmlinux" in content
        assert "源码就绪" in content
        assert "构建完成" in content

    def test_summary_timing(self, tmp_target):
        """摘要包含耗时信息。"""
        out = BuildOutput(tmp_target, level=OutputLevel.NORMAL)
        out._tty = False
        config = {"board": "b", "product": "p", "variant": "v"}

        buf = StringIO()
        with patch("sys.stdout", buf):
            out.build_start("image", config)
            out.phase_start("kernel")
            time.sleep(0.05)
            out.phase_end("kernel", success=True)
            out.build_end()

        text = strip_ansi(buf.getvalue())
        # 应包含秒数
        assert "s" in text
        assert "总耗时" in text


# ---------------------------------------------------------------------------
# 7.2 错误场景
# ---------------------------------------------------------------------------

class TestErrorScenarios:
    """验证错误上下文提取和失败摘要。"""

    def test_build_failure_shows_error_context(self, tmp_target):
        """命令失败时显示错误上下文。"""
        out = BuildOutput(tmp_target, level=OutputLevel.NORMAL)
        out._tty = False
        config = {"board": "b", "product": "p", "variant": "v"}

        buf = StringIO()
        with patch("sys.stdout", buf):
            out.build_start("image", config)
            out.phase_start("kernel")
            out.feed_line("CC drivers/gpu/foo.o\n")
            out.feed_line("drivers/gpu/foo.c:42: error: bad thing\n")
            out.feed_line("make[1]: *** [Makefile:100] Error 1\n")
            out.phase_end("kernel", success=False,
                          error=Exception("编译错误"))
            out.build_end()

        text = strip_ansi(buf.getvalue())
        # 错误上下文
        assert "error: bad thing" in text
        assert "┄" in text
        # 失败摘要
        assert "构建失败" in text
        assert "失败" in text

    def test_fallback_tail_when_no_error_pattern(self, tmp_target):
        """无匹配错误模式时显示最后 N 行。"""
        out = BuildOutput(tmp_target, level=OutputLevel.NORMAL)
        out._tty = False
        config = {"board": "b", "product": "p", "variant": "v"}

        buf = StringIO()
        with patch("sys.stdout", buf):
            out.build_start("image", config)
            out.phase_start("tool")
            for i in range(25):
                out.feed_line(f"some output line {i}\n")
            out.phase_end("tool", success=False,
                          error=Exception("unknown"))
            out.build_end()

        text = strip_ansi(buf.getvalue())
        # 应显示最后几行（tail buffer）
        assert "some output line 24" in text
        assert "┄" in text

    def test_error_log_contains_full_output(self, tmp_target):
        """build.log 包含完整错误输出。"""
        out = BuildOutput(tmp_target, level=OutputLevel.NORMAL)
        out._tty = False
        config = {"board": "b", "product": "p", "variant": "v"}

        with patch("sys.stdout", StringIO()):
            out.build_start("image", config)
            out.phase_start("kernel")
            out.feed_line("CC ok.o\n")
            out.feed_line("foo.c:1: error: fail\n")
            out.phase_end("kernel", success=False, error=Exception("err"))
            out.build_end()

        log_content = (tmp_target / "build.log").read_text()
        assert "CC ok.o" in log_content
        assert "error: fail" in log_content


# ---------------------------------------------------------------------------
# 7.3 Verbose/Quiet 模式
# ---------------------------------------------------------------------------

class TestOutputLevels:
    """验证不同 OutputLevel 下输出内容差异。"""

    def _run_build(self, tmp_target, level):
        out = BuildOutput(tmp_target, level=level)
        out._tty = False
        config = {"board": "b", "product": "p", "variant": "v"}
        buf = StringIO()
        with patch("sys.stdout", buf):
            out.build_start("image", config)
            out.phase_start("kernel")
            out.status("源码就绪")
            out.warning("一个警告")
            out.feed_line("CC init/main.o\n")
            out.phase_end("kernel", success=True)
            out.build_end()
        return strip_ansi(buf.getvalue())

    def test_normal_mode(self, tmp_target):
        text = self._run_build(tmp_target, OutputLevel.NORMAL)
        assert "源码就绪" in text
        assert "CC init/main.o" not in text  # L3 被压缩
        assert "警告" not in text  # warning 不显示

    def test_verbose_mode(self, tmp_target):
        text = self._run_build(tmp_target, OutputLevel.VERBOSE)
        assert "源码就绪" in text
        assert "CC init/main.o" in text  # L3 全量显示
        assert "警告" in text  # warning 显示

    def test_quiet_mode(self, tmp_target):
        text = self._run_build(tmp_target, OutputLevel.QUIET)
        assert "flange build" in text  # 横幅仍显示
        assert "源码就绪" not in text  # L2 status 被压缩
        assert "构建完成" in text  # 摘要仍显示
