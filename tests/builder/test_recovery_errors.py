"""§8 安全与错误处理 — 边界场景测试。

覆盖：
- 强制写入受保护分区的宿主侧二次确认（输入非 YES 时取消）
- 设备侧 --force 必须配合 --sha256 的二次校验
- AdbTransport.wait 超时
- 镜像过大、目标已挂载、sha256 不匹配（设备侧）已在 §6 / §7 测试中覆盖；
  这里挑选未覆盖的端到端衔接点
"""

from __future__ import annotations

import importlib.util
import io
import sys
import types
from pathlib import Path

import pytest

from builder.recovery_host import (
    AdbTransport,
    HostRecoveryError,
    ShellResult,
    Transport,
    cmd_flash,
)


# ── 加载 recoveryctl 脚本 ───────────────────────────────────────


_RC_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "components" / "app" / "recoveryctl" / "bin" / "recoveryctl"
)


def _load_rc():
    from importlib.machinery import SourceFileLoader
    loader = SourceFileLoader("recoveryctl_script", str(_RC_SCRIPT))
    spec = importlib.util.spec_from_loader("recoveryctl_script", loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("recoveryctl_script", mod)
    loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def rc():
    return _load_rc()


# ── 重用 §7 中的 FakeTransport 雏形 ────────────────────────────


class _FakeStreamingProc:
    def __init__(self, lines, returncode=0):
        text = "".join((l if l.endswith("\n") else l + "\n") for l in lines)
        self.stdout = io.StringIO(text)
        self.stderr = io.StringIO("")
        self._rc = returncode

    def wait(self, timeout=None):
        return self._rc

    def kill(self):
        self._rc = -9

    def poll(self):
        return self._rc


class FakeTransport(Transport):
    def __init__(self, *, mode: str = "recovery",
                 streaming_lines=None,
                 streaming_returncode: int = 0):
        self.mode = mode
        self.streaming_lines = list(streaming_lines or [
            "PORT=7654", "READY", "STATUS:OK", "__flange_rc__=0",
        ])
        self.streaming_returncode = streaming_returncode
        self.shell_calls: list[list[str]] = []
        self.shell_streaming_calls: list[list[str]] = []
        self.forward_calls: list[int] = []
        self.forward_remove_calls: list[int] = []
        self.push_calls: list = []

    def wait(self, timeout: int = 30) -> None:
        pass

    def push(self, local: Path, remote: str) -> None:
        self.push_calls.append((local, remote))

    def pull(self, remote: str, local: Path) -> None:
        pass

    def shell(self, args, *, capture=True):
        self.shell_calls.append(list(args))
        if args == ["recoveryctl", "mode"]:
            return ShellResult(0, self.mode + "\n", "")
        return ShellResult(0, "", "")

    def shell_streaming(self, args):
        self.shell_streaming_calls.append(list(args))
        return _FakeStreamingProc(self.streaming_lines, self.streaming_returncode)

    def forward(self, remote_port):
        self.forward_calls.append(remote_port)
        return 44321

    def forward_remove(self, local_port):
        self.forward_remove_calls.append(local_port)

    def interactive_shell(self) -> int:
        return 0


# ── 8.2 host 侧 --force 二次确认 ────────────────────────────────


class TestForceConfirmation:
    def test_no_confirm_cancels(self, tmp_path):
        img = tmp_path / "raw.img"
        img.write_bytes(b"\x00" * 8)
        t = FakeTransport()
        with pytest.raises(HostRecoveryError, match="未确认"):
            cmd_flash(t, partition="rootfs", image=img, force=True,
                      prompt=lambda *_: "n")

    def test_lowercase_yes_does_not_count(self, tmp_path):
        img = tmp_path / "raw.img"
        img.write_bytes(b"\x00" * 8)
        t = FakeTransport()
        with pytest.raises(HostRecoveryError, match="未确认"):
            cmd_flash(t, partition="rootfs", image=img, force=True,
                      prompt=lambda *_: "yes")

    def test_uppercase_yes_proceeds(self, tmp_path, monkeypatch):
        from builder import recovery_host as rh
        import socket as _socket
        import threading

        img = tmp_path / "raw.img"
        img.write_bytes(b"\x00" * 8)
        t = FakeTransport()
        server, client = _socket.socketpair()
        monkeypatch.setattr(rh, "_connect_local", lambda h, p: client)
        threading.Thread(
            target=lambda: [server.recv(4096) for _ in range(4)],
            daemon=True,
        ).start()
        rc = cmd_flash(t, partition="rootfs", image=img, force=True,
                       prompt=lambda *_: "YES")
        assert rc == 0
        # --force 应被透传到 recoveryctl flash
        assert len(t.shell_streaming_calls) == 1
        args = t.shell_streaming_calls[0]
        assert args[0:2] == ["recoveryctl", "flash"]
        assert "--force" in args

    def test_no_prompt_without_force(self, tmp_path, monkeypatch):
        """非 force 路径不应触发 prompt。"""
        from builder import recovery_host as rh
        import socket as _socket
        import threading

        img = tmp_path / "raw.img"
        img.write_bytes(b"\x00" * 8)
        t = FakeTransport()
        server, client = _socket.socketpair()
        monkeypatch.setattr(rh, "_connect_local", lambda h, p: client)
        threading.Thread(
            target=lambda: [server.recv(4096) for _ in range(4)],
            daemon=True,
        ).start()
        prompt_calls = []
        rc = cmd_flash(
            t, partition="rootfs", image=img, force=False,
            prompt=lambda *args: prompt_calls.append(args) or "no",
        )
        assert rc == 0
        assert prompt_calls == []
        assert len(t.shell_streaming_calls) == 1


# ── 8.2 device 侧 --force + 必须 --sha256 ─────────────────────


class TestDeviceForceRequiresSha(object):
    def _config(self) -> dict:
        return {
            "partitions": [
                {"name": "rootfs", "offset": "0x40000", "size": "0x200000",
                 "type": "ext4", "protected": False},
                {"name": "recovery", "offset": "0x240000", "size": "0x100000",
                 "type": "ext4", "protected": True},
            ],
        }

    def test_force_protected_without_sha_raises(self, rc):
        req = rc.FlashRequest(
            partition="recovery", size_bytes=16,
            sha256_expected=None, force=True,
        )
        with pytest.raises(rc.RecoveryError, match="--sha256"):
            rc.validate_flash(
                req, self._config(),
                block_size_lookup=lambda d: 1 << 30,
                mounted_lookup=lambda d: None,
                partition_resolver=lambda n: Path(f"/dev/{n}"),
            )

    def test_force_protected_with_sha_passes(self, rc):
        req = rc.FlashRequest(
            partition="recovery", size_bytes=16,
            sha256_expected="a" * 64, force=True,
        )
        dev = rc.validate_flash(
            req, self._config(),
            block_size_lookup=lambda d: 1 << 30,
            mounted_lookup=lambda d: None,
            partition_resolver=lambda n: Path(f"/dev/{n}"),
        )
        assert dev == Path("/dev/recovery")

    def test_unprotected_partition_still_requires_sha(self, rc):
        """stream flash 的完整性参数对所有分区都是控制面要求。"""
        req = rc.FlashRequest(
            partition="rootfs", size_bytes=16,
            sha256_expected=None, force=True,
        )
        with pytest.raises(rc.RecoveryError, match="--sha256"):
            rc.validate_flash(
                req, self._config(),
                block_size_lookup=lambda d: 1 << 30,
                mounted_lookup=lambda d: None,
                partition_resolver=lambda n: Path(f"/dev/{n}"),
            )


# ── 8.5 ADB transport wait 超时 ────────────────────────────────


class TestAdbWaitTimeout:
    def test_wait_times_out(self, monkeypatch, tmp_path):
        # 跳过 PATH 查找，直接构造 AdbTransport
        from builder import recovery_host as rh

        # 让 _run 永远返回 unknown 状态
        class Result:
            returncode = 0
            stdout = "unknown\n"
            stderr = ""

        def fake_run(self, args, *, capture=True, stdin=None):
            return Result()

        monkeypatch.setattr(rh.AdbTransport, "_run", fake_run)
        monkeypatch.setattr(rh.time, "sleep", lambda *a, **k: None)

        # 让 monotonic 时间走 5 步即超过 1 秒预算
        seq = iter([0, 0.2, 0.5, 1.5, 2.0, 2.5])
        monkeypatch.setattr(rh.time, "time", lambda: next(seq))

        t = rh.AdbTransport(adb_path="/usr/bin/false")
        with pytest.raises(rh.HostRecoveryError, match="等待 ADB 设备超时"):
            t.wait(timeout=1)


# ── 8.5 设备端 missing dependencies 衔接 ──────────────────────


class TestRecoveryctlAdditionalErrors:
    def test_image_too_large_for_protected_partition(self, rc):
        req = rc.FlashRequest(
            partition="recovery", size_bytes=1024,
            sha256_expected="a" * 64, force=True,
        )
        with pytest.raises(rc.RecoveryError, match="超过分区"):
            rc.validate_flash(
                req,
                {"partitions": [
                    {"name": "recovery", "offset": "0x240000", "size": "0x100000",
                     "type": "ext4", "protected": True},
                ]},
                block_size_lookup=lambda d: 100,  # tiny
                mounted_lookup=lambda d: None,
                partition_resolver=lambda n: Path(f"/dev/{n}"),
            )

    def test_already_mounted_with_force(self, rc):
        """挂载检查不被 --force 跳过。"""
        req = rc.FlashRequest(
            partition="recovery", size_bytes=16,
            sha256_expected="a" * 64, force=True,
        )
        with pytest.raises(rc.RecoveryError, match="已挂载"):
            rc.validate_flash(
                req,
                {"partitions": [
                    {"name": "recovery", "offset": "0x240000", "size": "0x100000",
                     "type": "ext4", "protected": True},
                ]},
                block_size_lookup=lambda d: 1 << 30,
                mounted_lookup=lambda d: "/mnt/recovery",
                partition_resolver=lambda n: Path(f"/dev/{n}"),
            )
