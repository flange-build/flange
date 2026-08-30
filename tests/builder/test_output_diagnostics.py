"""build.log 轮转/时间戳，与失败诊断的可读性。

**为什么需要它**：这两条是所有后续性能优化的前提 —— 在此之前，
`flange build` 失败时终端上可能一个原因都没有（异常原文从不打印，摘要按 40
字符硬截断），而 build.log 每次构建直接 truncate、且不带时间戳，既没法跟上
一次成功构建对比，也答不出"rootfs 这 8 分钟花在哪一步"。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from builder.output import BuildOutput, OutputLevel, rotate_log


# ---------------------------------------------------------------------------
# build.log 轮转
# ---------------------------------------------------------------------------

def test_轮转保留历史日志(tmp_path: Path):
    log = tmp_path / "build.log"

    for round_index in range(4):
        log.write_text(f"round-{round_index}\n")
        rotate_log(log, keep=3)

    assert not log.exists(), "轮转后原位置应空出来给新日志"
    assert (tmp_path / "build.log.1").read_text() == "round-3\n"
    assert (tmp_path / "build.log.2").read_text() == "round-2\n"
    assert (tmp_path / "build.log.3").read_text() == "round-1\n"
    assert not (tmp_path / "build.log.4").exists(), "超出 keep 的必须丢弃"


def test_keep为0时不轮转(tmp_path: Path):
    log = tmp_path / "build.log"
    log.write_text("x")
    rotate_log(log, keep=0)
    assert log.read_text() == "x"
    assert not (tmp_path / "build.log.1").exists()


def test_构造时轮转上一次构建的日志(tmp_path: Path):
    (tmp_path / "build.log").write_text("上一次构建\n")

    out = BuildOutput(tmp_path, OutputLevel.QUIET)
    out.close()

    assert (tmp_path / "build.log.1").read_text() == "上一次构建\n"
    # 只看正文：头部带 target= 路径，而 tmp_path 里含测试名，会误命中
    body = [line for line in (tmp_path / "build.log").read_text().splitlines()
            if not line.startswith("#")]
    assert not any("上一次构建" in line for line in body)


def test_环境变量可关闭轮转(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FLANGE_LOG_KEEP", "0")
    (tmp_path / "build.log").write_text("旧的\n")

    BuildOutput(tmp_path, OutputLevel.QUIET).close()

    assert not (tmp_path / "build.log.1").exists()


# ---------------------------------------------------------------------------
# 行级时间戳
# ---------------------------------------------------------------------------

def test_每行都带相对时间戳(tmp_path: Path, capsys):
    out = BuildOutput(tmp_path, OutputLevel.VERBOSE)
    out.feed_line("configure: 开始")
    out.feed_line("configure: 结束")
    out.close()
    capsys.readouterr()

    body = [line for line in (tmp_path / "build.log").read_text().splitlines()
            if not line.startswith("#")]
    assert body, "日志不能是空的"
    for line in body:
        assert line.startswith("[+"), f"缺时间戳: {line!r}"
        assert "s] " in line


def test_跨调用的半行不会被插进时间戳(tmp_path: Path, capsys):
    """spinner 与 end="" 的续写会把一行切成多次写入。

    每次写入都无条件加前缀，时间戳就会插到行中间，日志变得没法 grep。
    """
    out = BuildOutput(tmp_path, OutputLevel.VERBOSE)
    out._log_write("前半段")
    out._log_write("后半段\n")
    out.close()
    capsys.readouterr()

    body = [line for line in (tmp_path / "build.log").read_text().splitlines()
            if not line.startswith("#")]
    assert any(line.endswith("前半段后半段") for line in body), body
    assert not any("前半段[+" in line for line in body), "时间戳插进了行中间"


def test_日志头部记录绝对时间与target(tmp_path: Path, capsys):
    """相对时间戳答"哪一步慢"，绝对时间答"这份日志是哪次构建的"。"""
    BuildOutput(tmp_path, OutputLevel.QUIET).close()
    capsys.readouterr()

    head = (tmp_path / "build.log").read_text().splitlines()[0]
    assert "flange build.log" in head
    assert str(tmp_path) in head


# ---------------------------------------------------------------------------
# 失败诊断
# ---------------------------------------------------------------------------

def _fail_once(out: BuildOutput, error: Exception) -> str:
    out.build_start("golden-board", {})
    out.phase_start("rootfs")
    out.phase_end("rootfs", success=False, error=error)
    return ""


def test_异常原文出现在终端(tmp_path: Path, capsys):
    """核心回归：此前只打命令输出尾巴，flange 自己抛的异常一个字都不显示。"""
    out = BuildOutput(tmp_path, OutputLevel.NORMAL)
    _fail_once(out, ValueError("rootfs 分区 2G 装不下 3.1G 的镜像"))
    out.close()

    stdout = capsys.readouterr().out
    assert "rootfs 分区 2G 装不下 3.1G 的镜像" in stdout
    assert "ValueError" in stdout, "异常类型也要在，否则分不清是谁抛的"


def test_失败时给出完整日志路径(tmp_path: Path, capsys):
    out = BuildOutput(tmp_path, OutputLevel.NORMAL)
    _fail_once(out, RuntimeError("boom"))
    out.close()

    assert str(tmp_path / "build.log") in capsys.readouterr().out


def test_多行异常在终端保持多行(tmp_path: Path, capsys):
    out = BuildOutput(tmp_path, OutputLevel.NORMAL)
    _fail_once(out, RuntimeError("第一行结论\n第二行细节\n第三行建议"))
    out.close()

    stdout = capsys.readouterr().out
    for fragment in ("第一行结论", "第二行细节", "第三行建议"):
        assert fragment in stdout


def test_摘要取首行而不是前40字符(tmp_path: Path, capsys):
    """按字符截断会切在 Traceback 或路径中间；首行才是结论。"""
    out = BuildOutput(tmp_path, OutputLevel.NORMAL)
    out.build_start("golden-board", {})
    out.phase_start("kernel")
    out.phase_end("kernel", success=False,
                  error=RuntimeError("交叉编译器缺失：aarch64-linux-gnu-gcc\n"
                                     "Traceback (most recent call last):\n"
                                     "  File \"builder/kernel.py\", line 1"))
    out.build_end()

    stdout = capsys.readouterr().out
    summary = [l for l in stdout.splitlines() if "kernel" in l and "失败" in l]
    assert summary, stdout
    assert "Traceback" not in summary[0], "摘要不该带上 traceback"
    assert "交叉编译器缺失" in summary[0]


def test_无命令输出也能给出诊断(tmp_path: Path, capsys):
    """参数校验类失败没有任何命令输出 —— 正是此前完全静默的那一类。"""
    out = BuildOutput(tmp_path, OutputLevel.NORMAL)
    assert not out._errors and not out._tail_buffer
    _fail_once(out, ValueError("partitions.entries 为空"))
    out.close()

    assert "partitions.entries 为空" in capsys.readouterr().out


def test_traceback只进日志不进终端(tmp_path: Path, capsys):
    """终端要结论，排查的人要栈 —— 两者的读者不同，不该混在一起。"""
    out = BuildOutput(tmp_path, OutputLevel.NORMAL)
    try:
        raise RuntimeError("装配失败")
    except RuntimeError as error:
        out.build_start("golden-board", {})
        out.phase_start("image")
        out.phase_end("image", success=False, error=error)
    out.close()

    stdout = capsys.readouterr().out
    log = (tmp_path / "build.log").read_text()
    assert "装配失败" in stdout
    assert "Traceback" not in stdout, "终端不该刷栈"
    assert "Traceback" in log, "日志里必须留下栈，否则排查无从下手"
    assert "test_traceback只进日志不进终端" in log, "栈要能定位到抛出点"
