"""flange recovery 宿主机 CLI 单元测试（§7.10）。"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from builder.recovery_host import (
    HostRecoveryError,
    ShellResult,
    Transport,
    build_argparser,
    cmd_backup,
    cmd_enter,
    cmd_flash,
    cmd_list,
    cmd_reboot,
    main,
    query_device_mode,
    require_recovery_mode,
)


# ── 假 transport：把所有调用记录下来 ────────────────────────────


class _FakeStreamingProc:
    """模拟 shell_streaming 返回的 Popen：按预设序列吐 stdout 行。"""

    def __init__(self, lines: list[str], returncode: int = 0):
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
    def __init__(self, *, mode_sequence: list[str] | None = None,
                 list_payload: dict | None = None,
                 shell_returncode: int = 0,
                 shell_stderr: str = "",
                 streaming_lines: list[str] | None = None,
                 streaming_returncode: int = 0,
                 forward_local_port: int = 44321):
        self.mode_sequence = list(mode_sequence) if mode_sequence else ["recovery"]
        self.list_payload = list_payload
        self.shell_returncode = shell_returncode
        self.shell_stderr = shell_stderr
        self.streaming_lines = list(streaming_lines or [
            "PORT=7654",
            "READY",
            "STATUS:OK",
            "__flange_rc__=0",
        ])
        self.streaming_returncode = streaming_returncode
        self.forward_local_port = forward_local_port
        self.shell_calls: list[list[str]] = []
        self.shell_streaming_calls: list[list[str]] = []
        self.forward_calls: list[int] = []
        self.forward_remove_calls: list[int] = []
        self.push_calls: list[tuple[Path, str]] = []
        self.pull_calls: list[tuple[str, Path]] = []
        self.wait_calls: list[int] = []
        self.interactive_calls = 0

    def _next_mode(self) -> str:
        if self.mode_sequence:
            return self.mode_sequence.pop(0)
        return "recovery"

    def wait(self, timeout: int = 30) -> None:
        self.wait_calls.append(timeout)

    def push(self, local: Path, remote: str) -> None:
        self.push_calls.append((local, remote))

    def pull(self, remote: str, local: Path) -> None:
        self.pull_calls.append((remote, local))
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(b"backup-bytes")

    def shell(self, args: list[str], *, capture: bool = True) -> ShellResult:
        self.shell_calls.append(list(args))
        if args == ["recoveryctl", "mode"]:
            return ShellResult(0, self._next_mode() + "\n", "")
        if args == ["recoveryctl", "list", "--json"]:
            payload = self.list_payload or {
                "mode": "recovery",
                "board": "tspi-rk3566",
                "product": "default",
                "variant": "release",
                "transport": "adb",
                "partitions": [
                    {"name": "rootfs", "offset": "0x40000", "size": "0x200000",
                     "type": "ext4", "protected": False,
                     "mounted": False, "mountpoint": None},
                ],
            }
            return ShellResult(0, json.dumps(payload), "")
        return ShellResult(self.shell_returncode, "", self.shell_stderr)

    def shell_streaming(self, args: list[str]):
        self.shell_streaming_calls.append(list(args))
        return _FakeStreamingProc(self.streaming_lines, self.streaming_returncode)

    def forward(self, remote_port: int) -> int:
        self.forward_calls.append(remote_port)
        return self.forward_local_port

    def forward_remove(self, local_port: int) -> None:
        self.forward_remove_calls.append(local_port)

    def interactive_shell(self) -> int:
        self.interactive_calls += 1
        return 0


# ── argparse 解析（§7.10 参数解析） ──────────────────────────


class TestArgparser:
    def test_enter(self):
        ns = build_argparser().parse_args(["enter"])
        assert ns.cmd == "enter"

    def test_list_json(self):
        ns = build_argparser().parse_args(["list", "--json"])
        assert ns.cmd == "list" and ns.output_json is True

    def test_flash_required_args(self):
        ns = build_argparser().parse_args(["flash", "rootfs", "/tmp/img"])
        assert ns.cmd == "flash"
        assert ns.partition == "rootfs"
        assert ns.image == "/tmp/img"
        assert ns.force is False

    def test_flash_force(self):
        ns = build_argparser().parse_args(
            ["flash", "raw_part", "/tmp/img", "--force"])
        assert ns.force is True

    def test_backup_default_compress(self):
        ns = build_argparser().parse_args(["backup", "rootfs", "/tmp/o.zst"])
        assert ns.compress == "zstd"

    def test_backup_compress_none(self):
        ns = build_argparser().parse_args(
            ["backup", "rootfs", "/tmp/o.img", "--compress", "none"])
        assert ns.compress == "none"

    def test_reboot_default_normal(self):
        ns = build_argparser().parse_args(["reboot"])
        assert ns.target == "normal"

    def test_reboot_recovery(self):
        ns = build_argparser().parse_args(["reboot", "recovery"])
        assert ns.target == "recovery"

    def test_reboot_help_mentions_boot_once(self, capsys):
        with pytest.raises(SystemExit) as exc:
            build_argparser().parse_args(["reboot", "--help"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "reboot reason" in out
        assert "recovery.conf" in out
        assert "不持久修改 extlinux DEFAULT" in out


# ── ADB 缺失（§7.10） ───────────────────────────────────────


class TestAdbAvailability:
    def test_main_reports_missing_adb(self, capsys, monkeypatch):
        from builder import recovery_host as rh

        def boom():
            raise HostRecoveryError("未在 PATH 中找到 adb。请安装 ...")

        rc = rh.main(["enter"], transport_factory=boom)
        assert rc == 1
        err = capsys.readouterr().err
        assert "adb" in err


# ── enter / require_recovery_mode（§7.3） ───────────────────


class TestEnter:
    def test_already_recovery_short_circuits(self, capsys):
        t = FakeTransport(mode_sequence=["recovery"])
        rc = cmd_enter(t)
        assert rc == 0
        # 不应触发 reboot
        assert ["recoveryctl", "recovery"] not in t.shell_calls
        assert "已处于" in capsys.readouterr().out

    def test_normal_triggers_reboot_and_waits(self, monkeypatch, capsys):
        # 第一次查询 normal，重启后再次查询 recovery
        t = FakeTransport(mode_sequence=["normal", "recovery"])
        # 跳过 5s sleep
        import builder.recovery_host as rh
        monkeypatch.setattr(rh.time, "sleep", lambda *a, **k: None)
        rc = cmd_enter(t)
        assert rc == 0
        assert ["recoveryctl", "recovery"] in t.shell_calls
        # wait 应被调用至少两次（initial + 重启后）
        assert len(t.wait_calls) >= 2

    def test_normal_remains_normal_raises(self, monkeypatch):
        t = FakeTransport(mode_sequence=["normal", "normal"])
        import builder.recovery_host as rh
        monkeypatch.setattr(rh.time, "sleep", lambda *a, **k: None)
        with pytest.raises(HostRecoveryError, match="未能进入 recovery"):
            cmd_enter(t)


# ── flash 模式守卫（§7.10 normal 模式拒绝 flash） ───────────


class TestFlashModeGuard:
    def test_flash_in_normal_mode_rejected(self, tmp_path):
        img = tmp_path / "rootfs.img"
        img.write_bytes(b"\x00" * 16)
        t = FakeTransport(mode_sequence=["normal"])
        with pytest.raises(HostRecoveryError, match="recovery enter"):
            cmd_flash(t, partition="rootfs", image=img)

    def test_flash_rejects_block_device_partition(self, tmp_path):
        img = tmp_path / "x.img"
        img.write_bytes(b"x")
        t = FakeTransport(mode_sequence=["recovery"])
        with pytest.raises(HostRecoveryError, match="设备路径"):
            cmd_flash(t, partition="/dev/sda1", image=img)

    def test_flash_missing_image(self):
        t = FakeTransport(mode_sequence=["recovery"])
        with pytest.raises(HostRecoveryError, match="镜像文件"):
            cmd_flash(t, partition="rootfs", image=Path("/no/such.img"))

    def test_flash_streams_and_invokes_recoveryctl(self, tmp_path, monkeypatch):
        from builder import recovery_host as rh
        import socket as _socket
        import threading

        img = tmp_path / "rootfs.img"
        img.write_bytes(b"\x00" * 16)
        t = FakeTransport(mode_sequence=["recovery"])

        server, client = _socket.socketpair()
        monkeypatch.setattr(rh, "_connect_local", lambda h, p: client)

        received = []

        def reader():
            while True:
                buf = server.recv(4096)
                if not buf:
                    break
                received.append(buf)

        threading.Thread(target=reader, daemon=True).start()

        rc = cmd_flash(t, partition="rootfs", image=img)
        assert rc == 0
        assert t.push_calls == []
        assert len(t.shell_streaming_calls) == 1
        args = t.shell_streaming_calls[0]
        assert args[:3] == ["recoveryctl", "flash", "rootfs"]
        assert "--size" in args
        assert "--sha256" in args
        assert "--listen" in args
        assert t.forward_calls == [7654]

    def test_flash_force_streams_force_and_readback(self, tmp_path, monkeypatch):
        from builder import recovery_host as rh
        import socket as _socket
        import threading

        img = tmp_path / "boot.img"
        img.write_bytes(b"\x00" * 16)
        t = FakeTransport(mode_sequence=["recovery"])

        server, client = _socket.socketpair()
        monkeypatch.setattr(rh, "_connect_local", lambda h, p: client)
        threading.Thread(
            target=lambda: [server.recv(4096) for _ in range(4)],
            daemon=True,
        ).start()

        rc = cmd_flash(
            t, partition="boot", image=img, force=True,
            prompt=lambda _: "YES",
        )
        assert rc == 0
        args = t.shell_streaming_calls[0]
        assert "--force" in args
        assert "--verify-readback" in args
        assert "--listen" in args

    def test_flash_rejects_file_changed_during_hash(self, tmp_path, monkeypatch):
        from builder import recovery_host as rh

        img = tmp_path / "rootfs.img"
        img.write_bytes(b"before")
        real_sha = rh._sha256_of_file

        def mutating_sha(path):
            digest = real_sha(path)
            path.write_bytes(b"after")
            return digest

        monkeypatch.setattr(rh, "_sha256_of_file", mutating_sha)
        t = FakeTransport(mode_sequence=["recovery"])
        with pytest.raises(HostRecoveryError, match="传输前后发生变化"):
            cmd_flash(t, partition="rootfs", image=img)
        assert t.shell_streaming_calls == []

    def test_flash_failure_reports_partial_write_risk(self, tmp_path, monkeypatch):
        from builder import recovery_host as rh
        import socket as _socket
        import threading

        img = tmp_path / "rootfs.img"
        img.write_bytes(b"\x00" * 16)
        t = FakeTransport(
            mode_sequence=["recovery"],
            streaming_lines=[
                "PORT=7654", "READY",
                "STATUS:FAIL:sha-mismatch",
                "__flange_rc__=1",
            ],
            streaming_returncode=1,
        )
        server, client = _socket.socketpair()
        monkeypatch.setattr(rh, "_connect_local", lambda h, p: client)
        threading.Thread(
            target=lambda: [server.recv(4096) for _ in range(4)],
            daemon=True,
        ).start()
        with pytest.raises(HostRecoveryError, match="可能已部分写入"):
            cmd_flash(t, partition="rootfs", image=img)


# ── list 格式化（§7.10） ────────────────────────────────────


class TestList:
    def test_list_json_passthrough(self, capsys):
        payload = {
            "mode": "recovery", "board": "tspi", "product": "default",
            "variant": "release", "transport": "adb",
            "partitions": [],
        }
        t = FakeTransport(list_payload=payload)
        rc = cmd_list(t, output_json=True)
        assert rc == 0
        out = capsys.readouterr().out
        assert json.loads(out) == payload

    def test_list_human_format(self, capsys):
        payload = {
            "mode": "recovery", "board": "tspi", "product": "default",
            "variant": "release", "transport": "adb",
            "partitions": [
                {"name": "rootfs", "offset": "0x40000", "size": "0x200000",
                 "type": "ext4", "protected": False,
                 "mounted": True, "mountpoint": "/mnt/rootfs"},
                {"name": "recovery", "offset": "0x240000", "size": "0x100000",
                 "type": "ext4", "protected": True,
                 "mounted": False, "mountpoint": None},
            ],
        }
        t = FakeTransport(list_payload=payload)
        cmd_list(t, output_json=False)
        out = capsys.readouterr().out
        assert "mode: recovery" in out
        assert "rootfs" in out
        assert "recovery" in out
        assert "/mnt/rootfs" in out


# ── backup ──────────────────────────────────────────────────


class TestBackup:
    def test_backup_streams_to_partial_then_renames(self, tmp_path, monkeypatch):
        from builder import recovery_host as rh
        import socket as _socket
        import threading

        out = tmp_path / "rootfs-backup.img.zst"
        payload = b"compressed-bytes" * 100

        server, client = _socket.socketpair()

        def writer():
            server.sendall(payload)
            server.shutdown(_socket.SHUT_WR)
            server.close()

        threading.Thread(target=writer).start()

        monkeypatch.setattr(rh, "_connect_local", lambda h, p: client)

        t = FakeTransport(mode_sequence=["recovery"])
        rc = cmd_backup(t, partition="rootfs", output=out)
        assert rc == 0
        assert out.exists()
        assert out.read_bytes() == payload
        assert not (tmp_path / "rootfs-backup.img.zst.partial").exists()
        assert t.push_calls == []
        assert t.pull_calls == []
        backup_calls = [c for c in t.shell_streaming_calls
                        if c[0:2] == ["recoveryctl", "backup"]]
        assert len(backup_calls) == 1
        assert "--listen" in backup_calls[0]
        assert "--compress" in backup_calls[0]

    def test_backup_in_normal_mode_rejected(self, tmp_path):
        t = FakeTransport(mode_sequence=["normal"])
        with pytest.raises(HostRecoveryError, match="recovery enter"):
            cmd_backup(t, partition="rootfs", output=tmp_path / "x")


# ── reboot ──────────────────────────────────────────────────


class TestReboot:
    def test_reboot_invalid_target(self):
        t = FakeTransport()
        with pytest.raises(HostRecoveryError, match="normal、recovery 或 loader"):
            cmd_reboot(t, target="garbage")

    def test_reboot_normal(self):
        t = FakeTransport()
        rc = cmd_reboot(t, target="normal")
        assert rc == 0
        assert ["recoveryctl", "normal"] in t.shell_calls

    def test_reboot_loader(self):
        t = FakeTransport()
        rc = cmd_reboot(t, target="loader")
        assert rc == 0
        assert ["recoveryctl", "loader"] in t.shell_calls
