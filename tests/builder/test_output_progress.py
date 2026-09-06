"""阶段顺序、真实动作计时与非交互输出的行为回归。"""

from __future__ import annotations

import time
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from builder.output import BuildOutput, OutputLevel, strip_ansi
from builder.term import display_width


@pytest.fixture()
def out(tmp_path: Path) -> BuildOutput:
    output = BuildOutput(tmp_path, level=OutputLevel.NORMAL)
    output._tty = False
    output._sticky_enabled = False
    return output


def _run(out: BuildOutput, body) -> str:
    buf = StringIO()
    with patch("sys.stdout", buf):
        body()
    return strip_ansi(buf.getvalue())


# ---------------------------------------------------------------------------
# 进度模型
# ---------------------------------------------------------------------------

def test_组件标题带序号(out: BuildOutput):
    def body():
        out.plan(["kernel", "rootfs", "image"])
        out.build_start("image", {"board": "b"})
        out.phase_start("rootfs")
        out.phase_end("rootfs")

    text = _run(out, body)
    assert "[2/3]" in text


def test_没有计划时不显示序号(out: BuildOutput):
    """`plan()` 未注入时不能瞎编分母。"""
    def body():
        out.build_start("image", {"board": "b"})
        out.phase_start("rootfs")
        out.phase_end("rootfs")

    text = _run(out, body)
    assert "[" not in text.split("rootfs")[1].split("\n")[0]


def test_计划外的组件不显示序号(out: BuildOutput):
    def body():
        out.plan(["kernel"])
        out.build_start("image", {"board": "b"})
        out.phase_start("rootfs")
        out.phase_end("rootfs")

    text = _run(out, body)
    assert "/1]" not in text


# ---------------------------------------------------------------------------
# 跳过原因
# ---------------------------------------------------------------------------

def test_区分缓存命中与配置关闭(out: BuildOutput):
    """两者是不同的事：前者产物已就绪，后者根本不参与本次构建。

    原实现共用"无变更，跳过"，会让人以为关掉的组件留着陈旧产物。
    """
    def body():
        out.plan(["rootfs", "amp"])
        out.build_start("image", {"board": "b"})
        out.phase_skip("rootfs", reason="cached")
        out.phase_skip("amp", reason="disabled")

    text = _run(out, body)
    assert "⊘ rootfs" in text and "缓存命中" in text
    assert "⊘ amp" in text and "配置关闭" in text


def test_跳过是单行(out: BuildOutput):
    """跳过的组件通常占多数，每个两行会把真正在构建的挤出屏幕。"""
    def body():
        out.plan(["a", "b", "c"])
        out.build_start("image", {"board": "b"})
        for name in ("a", "b", "c"):
            out.phase_skip(name)

    lines = [line for line in _run(out, body).splitlines() if "⊘" in line]
    assert len(lines) == 3


def test_跳过原因进摘要(out: BuildOutput):
    def body():
        out.plan(["amp"])
        out.build_start("image", {"board": "b"})
        out.phase_skip("amp", reason="disabled")
        out.build_end()

    assert "配置关闭" in _run(out, body)


# ---------------------------------------------------------------------------
# 步骤耗时自动测量
# ---------------------------------------------------------------------------

def test_步骤行带耗时(out: BuildOutput):
    """动作耗时只能通过明确的起止边界测量。"""
    def body():
        out.plan(["rootfs"])
        out.build_start("image", {"board": "b"})
        out.phase_start("rootfs")
        out.spinner_start("安装内核模块")
        time.sleep(0.12)
        out.spinner_stop()
        out.status("导出包清单")
        out.phase_end("rootfs")

    text = _run(out, body)
    module_line = [line for line in text.splitlines() if "安装内核模块" in line and "✔" in line][0]
    assert "✔" in module_line
    assert "0.1s" in module_line or "0.2s" in module_line


def test_极短步骤不标耗时(out: BuildOutput):
    """纯信息行（"跳过重置与补丁"一类）标个 0.0s 只是噪声。"""
    def body():
        out.plan(["rootfs"])
        out.build_start("image", {"board": "b"})
        out.phase_start("rootfs")
        out.status("local_path 源码：跳过重置与补丁")
        out.status("下一步")
        out.phase_end("rootfs")

    line = [line for line in _run(out, body).splitlines() if "跳过重置" in line][0]
    assert "0.0s" not in line


def test_最后一个步骤在组件结束时落盘(out: BuildOutput):
    """否则每个组件的最后一步永远不出现。"""
    def body():
        out.plan(["rootfs"])
        out.build_start("image", {"board": "b"})
        out.phase_start("rootfs")
        out.status("生成 rootfs.img")
        out.phase_end("rootfs")

    assert "生成 rootfs.img" in _run(out, body)


def test_失败时未完成的步骤仍落盘(out: BuildOutput):
    """否则"卡在哪一步失败的"这个最关键的信息会丢掉。"""
    def body():
        out.plan(["recovery"])
        out.build_start("image", {"board": "b"})
        out.phase_start("recovery")
        out.spinner_start("生成 recovery.img")
        out.phase_end("recovery", success=False, error=RuntimeError("装不下"))
        out.build_end(success=False)

    text = _run(out, body)
    assert "生成 recovery.img" in text and "装不下" in text
    step = next(line for line in text.splitlines() if "生成 recovery.img" in line and "✖" in line)
    assert "✖" in step and "✔" not in step


def test_取消时步骤与构建摘要不显示成功(out: BuildOutput):
    def body():
        out.build_start("image", {"board": "b"})
        out.phase_start("kernel")
        out.spinner_start("编译内核")
        try:
            raise KeyboardInterrupt
        except KeyboardInterrupt:
            out.build_end(success=False)

    text = _run(out, body)
    assert "⚠ 编译内核（已取消）" in text
    assert "⚠ 构建已取消" in text
    assert "✔" not in text and "构建失败" not in text


def test_关闭输出不把未确认的步骤标为成功(out: BuildOutput):
    def body():
        out.spinner_start("编译内核")
        out.close()

    text = _run(out, body)
    assert "编译内核" in text
    assert "✔" not in text


def test_组件显式取消不会先显示失败再显示取消(out: BuildOutput):
    def body():
        out.build_start("image", {"board": "b"})
        out.phase_start("kernel")
        out.spinner_start("编译内核")
        out.phase_end("kernel", success=False, error=KeyboardInterrupt())
        out.build_end(success=False)

    text = _run(out, body)
    assert "⚠ 编译内核（已取消）" in text
    assert "⚠ 已取消" in text and "⚠ 构建已取消" in text
    assert "✖ 失败" not in text and "构建失败" not in text and "✔" not in text


def test_非TTY同样保留步骤耗时(out: BuildOutput):
    """CI 日志正是事后查"时间花在哪"的地方。

    退化成立即打印一行不带耗时的 `· 步骤名`，等于把这个信息永久丢掉。
    """
    assert not out._sticky_enabled

    def body():
        out.plan(["rootfs"])
        out.build_start("image", {"board": "b"})
        out.phase_start("rootfs")
        out.spinner_start("安装内核模块")
        time.sleep(0.12)
        out.phase_end("rootfs")

    line = [line for line in _run(out, body).splitlines() if "安装内核模块" in line and "✔" in line][0]
    assert "✔" in line and "s" in line


# ---------------------------------------------------------------------------
# 宽度自适应
# ---------------------------------------------------------------------------

def test_布局敏感的行不超出终端宽度(out: BuildOutput, monkeypatch):
    """中文占两列，按字符数算宽度会让行溢出、表格错位。

    **文件路径不在此列**：截断路径等于让它没法用来打开文件，折行则会被
    终端的双击选中当成两段。路径就该让终端自己软换行。
    """
    monkeypatch.setattr("builder.output.terminal_width", lambda: 80)

    def body():
        out.plan(["device-tree-overlay", "rootfs"])
        out.build_start("image", {"board": "radxa-rock5b", "product": "desktop",
                                  "variant": "debug"})
        out.phase_skip("device-tree-overlay")
        out.phase_start("rootfs")
        out.status("导出已安装包清单并校验内容")
        out.phase_end("rootfs", success=False,
                      error=RuntimeError("内容约 449MB，算上 ext4 元数据开销"
                                         "需要至少 485MB；当前 image_size 仅 "
                                         "460MB，请增大 recovery 分区 image_size"))
        out.build_end()

    for line in _run(out, body).splitlines():
        if "build.log" in line:
            continue  # 路径不截断也不折行，见 docstring
        assert display_width(line) <= 80, f"超宽: {display_width(line)} {line!r}"


def test_长组件名不挤掉状态列(out: BuildOutput):
    """原实现固定 12 列，`device-tree-overlay` 19 个字符直接把状态列挤没。"""
    def body():
        out.plan(["device-tree-overlay"])
        out.build_start("image", {"board": "b"})
        out.phase_skip("device-tree-overlay")
        out.build_end()

    summary = [line for line in _run(out, body).splitlines()
               if "device-tree-overlay" in line and "缓存命中" in line]
    assert summary, "摘要里组件名与状态挤到了一起"
    assert "device-tree-overlay缓存命中" not in "".join(summary)


def test_异常原文折行而不截断(out: BuildOutput, monkeypatch):
    """异常原文是定位问题最关键的一句，截断会砍掉半句。"""
    monkeypatch.setattr("builder.output.terminal_width", lambda: 60)
    long_error = "配置校验失败：" + "分区 rootfs 与 recovery 重叠；" * 4

    def body():
        out.plan(["image"])
        out.build_start("image", {"board": "b"})
        out.phase_start("image")
        out.phase_end("image", success=False, error=ValueError(long_error))
        out.build_end(success=False)

    text = _run(out, body)
    assert "…" not in text.split("原因")[1].split("日志")[0]
    assert long_error[-12:] in text.replace("\n", "")


# ---------------------------------------------------------------------------
# 粘性底栏只在交互终端出现
# ---------------------------------------------------------------------------

def test_非TTY不启用底栏(tmp_path: Path):
    output = BuildOutput(tmp_path, level=OutputLevel.NORMAL)
    output._tty = False
    assert not output._sticky_enabled or not output._sticky_line()


def test_QUIET与VERBOSE不启用底栏(tmp_path: Path):
    """QUIET 不该有动画；VERBOSE 下原始命令输出含控制字符，会打乱行数记账。"""
    for level in (OutputLevel.QUIET, OutputLevel.VERBOSE):
        output = BuildOutput(tmp_path, level=level)
        assert not output._sticky_enabled


def test_底栏内容不进日志(tmp_path: Path):
    """底栏是纯终端呈现；混进日志会让日志充满进度条残片。"""
    output = BuildOutput(tmp_path, level=OutputLevel.NORMAL)
    output._tty = False

    def body():
        output.plan(["rootfs"])
        output.build_start("image", {"board": "b"})
        output.phase_start("rootfs")
        output.status("安装内核模块")
        output.phase_end("rootfs")
        output.build_end()

    _run(output, body)
    log = (tmp_path / "build.log").read_text()
    assert "\033" not in log
    for glyph in ("━", "╸", "⠋", "⠙"):
        assert glyph not in log


def test_底栏单行含进度与当前步骤(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("builder.output.terminal_width", lambda: 80)
    output = BuildOutput(tmp_path, level=OutputLevel.NORMAL)
    output._sticky_enabled = True
    output.plan(["kernel", "rootfs", "image"])
    output._build_start_time = time.monotonic()
    output._current_component = "rootfs"
    output._done_components = 1
    output._step_label = "安装内核模块"
    output._step_start = time.monotonic()

    line = strip_ansi(output._sticky_line())

    assert "\n" not in line
    assert "rootfs" in line and "安装内核模块" in line
    assert "[2/3]" in line and "%" not in line
    assert "已用" in line
    assert display_width(line) < 80

    with patch("sys.stdout", StringIO()) as stdout:
        output._draw_sticky()
        output._erase_sticky()
        output._draw_sticky()
    assert "\n" not in stdout.getvalue()


def test_停止底栏后不再重绘(tmp_path: Path):
    """只停线程不关重绘的话，构建摘要每打一行都会被重新贴上一条底栏，
    最后屏幕上还留着一条写着 100% 的进度条。"""
    output = BuildOutput(tmp_path, level=OutputLevel.NORMAL)
    output._sticky_enabled = True
    output._sticky_stop()
    assert not output._sticky_enabled


# ---------------------------------------------------------------------------
# 命令自成一步：耗时归属必须落在真正执行的东西上
# ---------------------------------------------------------------------------

def test_命令的耗时不算到上一行状态头上(out: BuildOutput):
    """实测出现过 `✔ flange_overrides.config 生成  2m14s` —— 那 2 分钟是
    紧随其后的内核编译，被算到了上一行状态头上。

    误导性的耗时比没有耗时更糟：它读起来像是生成一个 config 文件花了两分钟。
    """
    def body():
        out.plan(["kernel"])
        out.build_start("image", {"board": "b"})
        out.phase_start("kernel")
        out.status("flange_overrides.config 生成")
        out.spinner_start("编译内核...")
        time.sleep(0.15)
        out.spinner_stop()
        out.phase_end("kernel")

    lines = _run(out, body).splitlines()
    config_line = [line for line in lines if "flange_overrides" in line][0]
    compile_line = [line for line in lines if "编译内核" in line and "✔" in line][0]

    assert "2m" not in config_line and "0.1s" not in config_line
    assert "0.1s" in compile_line or "0.2s" in compile_line


def test_命令结束后留下结果行(out: BuildOutput):
    """原实现只擦掉 spinner 什么都不留（尽管 docstring 写着"替换为结果行"），
    于是最耗时的那条命令在终端上没有任何痕迹。"""
    def body():
        out.plan(["rootfs"])
        out.build_start("image", {"board": "b"})
        out.phase_start("rootfs")
        out.spinner_start("安装 52 个包...")
        time.sleep(0.12)
        out.spinner_stop()
        out.phase_end("rootfs")

    line = [line for line in _run(out, body).splitlines() if "安装 52 个包" in line and "✔" in line][0]
    assert "✔" in line and "s" in line


def test_命令标签去掉尾部省略号(out: BuildOutput):
    """`编译内核...` 是"正在进行"的措辞；落成完成行时该收掉。"""
    def body():
        out.plan(["kernel"])
        out.build_start("image", {"board": "b"})
        out.phase_start("kernel")
        out.spinner_start("编译内核...")
        out.spinner_stop()
        out.phase_end("kernel")

    line = [line for line in _run(out, body).splitlines() if "编译内核" in line and "✔" in line][0]
    assert "编译内核..." not in line


def test_同名的状态与命令合成一步(out: BuildOutput):
    """builder 常常先 `_status("编译 X...")` 再 `docker.run(label="编译 X...")`。

    落成两行、其中一行还没有耗时，纯属噪声 —— 实测输出里出现过
    `✔ 编译 rtl8852be (...)` 连续两行。
    """
    def body():
        out.plan(["kernel"])
        out.build_start("image", {"board": "b"})
        out.phase_start("kernel")
        out.status("编译 rtl8852be (rkwifibt vendor driver)...")
        out.spinner_start("编译 rtl8852be (rkwifibt vendor driver)...")
        time.sleep(0.12)
        out.spinner_stop()
        out.phase_end("kernel")

    lines = [line for line in _run(out, body).splitlines() if "rtl8852be" in line]
    assert len(lines) == 2, f"非 TTY 应只有开始与完成两条: {lines}"
    assert "·" in lines[0] and "✔" in lines[1]
    assert "0.1s" in lines[1] or "0.2s" in lines[1]


def test_不同名的状态与命令仍是两步(out: BuildOutput):
    """去重只针对完全同名的相邻项，不能把真正的两步吞掉。"""
    def body():
        out.plan(["kernel"])
        out.build_start("image", {"board": "b"})
        out.phase_start("kernel")
        out.status("准备 defconfig")
        time.sleep(0.08)
        out.spinner_start("编译内核...")
        time.sleep(0.08)
        out.spinner_stop()
        out.phase_end("kernel")

    text = _run(out, body)
    assert "准备 defconfig" in text and "编译内核" in text
