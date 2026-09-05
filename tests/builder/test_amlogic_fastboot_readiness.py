"""验证 USB 模式切换期间的等待、进程回收与写入边界，不连接真实设备。"""

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from builder.flash import AmlogicFlashStrategy, DeviceInfo, FlashConfig, FlashError
from builder.flash.execute import FlashExecutor
from builder.flash.model import FlashPartition, PreFlashConfig

TOOL = Path("/fastboot")
SERIAL = "vim3-serial"


def completed(stdout="", stderr=""):
    return subprocess.CompletedProcess([], 0, stdout, stderr)


@pytest.fixture
def clock(monkeypatch):
    state = SimpleNamespace(now=0.0)

    def advance(seconds):
        state.now += seconds

    state.advance = advance
    monkeypatch.setattr("builder.flash.strategy.time.monotonic", lambda: state.now)
    monkeypatch.setattr("builder.flash.strategy.time.sleep", advance)
    return state


@pytest.mark.parametrize("failed_phase", ["devices", "getvar"])
def test_delayed_enumeration_and_first_probe_timeout_recover(clock, failed_phase):
    strategy = AmlogicFlashStrategy()
    commands = []
    failed = False

    def run(cmd, **kwargs):
        nonlocal failed
        commands.append(cmd)
        if len(commands) == 1:
            return completed()  # U-Boot 仍在切换 USB 模式。
        if failed_phase in cmd and not failed:
            failed = True
            clock.advance(kwargs["timeout"])
            raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])
        if cmd[-1] == "devices":
            return completed(f"{SERIAL}\tfastboot\n")
        if "getvar" in cmd:
            return completed(stderr="version: 0.4\nFinished. Total time: 0.002s\n")
        return completed()

    with patch("builder.flash.strategy.subprocess.run", side_effect=run):
        strategy._wait_fastboot_ready(TOOL)
        assert failed
        assert all("oem" not in cmd and "flash" not in cmd for cmd in commands)
        strategy.write_gpt(TOOL, Path("/target"), None)
    assert commands[-2] == [str(TOOL), "-s", SERIAL, "getvar", "version"]
    assert commands[-1] == [str(TOOL), "-s", SERIAL, "oem", "format"]
    assert sum("oem" in cmd for cmd in commands) == 1


@pytest.mark.parametrize(
    "failure", ["absent", "enumeration", "handshake", "empty", "error"]
)
def test_unready_device_stops_at_total_deadline_without_writes(clock, failure):
    strategy = AmlogicFlashStrategy()
    strategy.FASTBOOT_WAIT_TIMEOUT = 7
    # 上次成功的状态不可在这次失败后复用。
    strategy._fastboot_serial = "old-device"
    probes = []

    def run(cmd, **kwargs):
        assert "oem" not in cmd and "flash" not in cmd and "reboot" not in cmd
        assert 0 < kwargs["timeout"] <= min(5, 7 - clock.now)
        probes.append(cmd)
        if failure == "error":
            raise subprocess.CalledProcessError(1, cmd, stderr="USB unavailable")
        if failure == "absent":
            return completed()
        if cmd[-1] == "devices" and failure != "enumeration":
            return completed(f"{SERIAL}\tfastboot\n")
        if failure == "empty":
            return completed(stderr="version: \nFinished. Total time: 0.001s\n")
        clock.advance(kwargs["timeout"])
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    with patch("builder.flash.strategy.subprocess.run", side_effect=run):
        with pytest.raises(FlashError, match="尚未写入 GPT 或分区"):
            strategy._wait_fastboot_ready(TOOL)
        count = len(probes)
        with pytest.raises(FlashError, match="尚未完成就绪握手"):
            strategy.write_gpt(TOOL, Path("/target"), None)
        assert len(probes) == count
    assert clock.now == 7
    assert strategy._fastboot_serial is None


@pytest.mark.parametrize("second", ["other-device", SERIAL])
def test_multiple_devices_are_rejected_before_handshake(second):
    strategy = AmlogicFlashStrategy()
    with (
        patch(
            "builder.flash.strategy.subprocess.run",
            return_value=completed(
                f"{SERIAL}\tfastboot\n{second}\tfastboot\n",
            ),
        ) as run,
        pytest.raises(FlashError, match="多台 fastboot"),
    ):
        strategy._wait_fastboot_ready(TOOL)
    assert run.call_count == 1
    assert strategy._fastboot_serial is None


@pytest.mark.parametrize(
    "output", ["warning: no devices\n", "no permissions\n", "serial\tadb\n"]
)
def test_unrelated_output_is_not_a_device(output):
    strategy = AmlogicFlashStrategy()
    with (
        patch.object(strategy, "_probe_maskrom", return_value=False),
        patch("builder.flash.strategy.subprocess.run", return_value=completed(output)),
    ):
        assert strategy.detect_device(TOOL) is None


@pytest.mark.parametrize("output", ["version: 0.4\n", "(bootloader) version: 0.4\n"])
def test_version_response_on_stdout_is_accepted(output):
    strategy = AmlogicFlashStrategy()
    with patch(
        "builder.flash.strategy.subprocess.run",
        side_effect=[
            completed(f"{SERIAL}\tfastboot\n"),
            completed(output),
        ],
    ):
        strategy._wait_fastboot_ready(TOOL)
    assert strategy._fastboot_serial == SERIAL


def test_interruption_is_not_retried():
    strategy = AmlogicFlashStrategy()
    with (
        patch(
            "builder.flash.strategy.subprocess.run", side_effect=KeyboardInterrupt
        ) as run,
        pytest.raises(KeyboardInterrupt),
    ):
        strategy._wait_fastboot_ready(TOOL)
    run.assert_called_once()
    assert strategy._fastboot_serial is None


@pytest.mark.parametrize("no_wait", [False, True])
@pytest.mark.parametrize("failure", ["handshake", "format_timeout", "format_error"])
def test_executor_never_continues_after_readiness_or_gpt_failure(
    tmp_path, clock, no_wait, failure
):
    config = FlashConfig(
        "amlogic",
        "fastboot",
        "khadas-vim3",
        "default",
        "debug",
        pre_flash=PreFlashConfig(download_boot="bootloader/u-boot.bin"),
        partitions=[
            FlashPartition(
                name="boot",
                offset="0",
                size="64M",
                type="raw",
                image="boot/boot.img",
            )
        ],
    )
    config.to_json(tmp_path / "flash-config.json")
    for relative in ("bootloader/u-boot.bin", "boot/boot.img"):
        image = tmp_path / relative
        image.parent.mkdir()
        image.write_bytes(b"test")
    executor = FlashExecutor(tmp_path)
    strategy = executor.strategy
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        if "devices" in cmd:
            return completed(f"{SERIAL}\tfastboot\n")
        if "getvar" in cmd:
            if failure == "handshake":
                clock.advance(kwargs["timeout"])
                raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])
            return completed(stderr="version: 0.4\n")
        if "oem" in cmd:
            assert kwargs["timeout"] == 30
            assert cmd == [str(TOOL), "-s", SERIAL, "oem", "format"]
            if failure == "format_error":
                raise subprocess.CalledProcessError(1, cmd)
            raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])
        assert cmd[0] == "sudo"  # --no-wait 路径仍上传 U-Boot，再完成握手。
        return completed()

    with (
        patch.object(strategy, "find_tool", return_value=TOOL),
        patch.object(
            strategy,
            "wait_for_device",
            return_value=DeviceInfo("amlogic", "fastboot", ""),
        ),
        patch.object(strategy, "_wait_maskrom_device"),
        patch.object(strategy, "_resolve_pyamlboot_entry", return_value="/boot-g12.py"),
        patch.object(strategy, "_darwin_dyld_lib_path", return_value=None),
        patch("shutil.which", return_value="/boot-g12.py"),
        patch("builder.flash.strategy.subprocess.run", side_effect=run),
    ):
        error = (
            subprocess.CalledProcessError if failure == "format_error" else FlashError
        )
        with pytest.raises(error) as caught:
            executor.flash_all(no_wait=no_wait)
    assert all("flash" not in cmd and "reboot" not in cmd for cmd in calls)
    assert sum("oem" in cmd for cmd in calls) == (0 if failure == "handshake" else 1)
    if failure == "format_timeout":
        assert "设备端执行结果未知" in str(caught.value)


def test_hung_probe_process_is_reaped_before_retry(tmp_path):
    """真实运行假工具，验证首次 USB 会话卡住后可自动恢复且无残留进程。"""
    tool = tmp_path / "fastboot"
    pid_file = tmp_path / "first-probe.pid"
    tool.write_text(
        f"#!{sys.executable}\n"
        + """
import os
import sys
import time
from pathlib import Path

pid_file = Path(__file__).with_name("first-probe.pid")
if sys.argv[1:] == ["devices"]:
    print("vim3-serial\\tfastboot")
elif sys.argv[1:] == ["-s", "vim3-serial", "getvar", "version"]:
    if not pid_file.exists():
        pid_file.write_text(str(os.getpid()))
        time.sleep(60)
    print("version: 0.4", file=sys.stderr)
else:
    sys.exit("禁止在测试工具中执行写入命令")
"""
    )
    tool.chmod(0o755)
    strategy = AmlogicFlashStrategy()
    strategy.FASTBOOT_WAIT_TIMEOUT = 8
    strategy.FASTBOOT_PROBE_TIMEOUT = 0.5
    strategy._wait_fastboot_ready(tool)
    assert strategy._fastboot_serial == SERIAL
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)
