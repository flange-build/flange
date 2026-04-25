"""flange recovery 宿主机 CLI 单元测试（§7.10）。"""

from __future__ import annotations

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


class FakeTransport(Transport):
    def __init__(self, *, mode_sequence: list[str] | None = None,
                 list_payload: dict | None = None,
                 shell_returncode: int = 0,
                 shell_stderr: str = ""):
        self.mode_sequence = list(mode_sequence) if mode_sequence else ["recovery"]
        self.list_payload = list_payload
        self.shell_returncode = shell_returncode
        self.shell_stderr = shell_stderr
        self.shell_calls: list[list[str]] = []
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
        assert ["recoveryctl", "reboot", "recovery"] not in t.shell_calls
        assert "已处于" in capsys.readouterr().out

    def test_normal_triggers_reboot_and_waits(self, monkeypatch, capsys):
        # 第一次查询 normal，重启后再次查询 recovery
        t = FakeTransport(mode_sequence=["normal", "recovery"])
        # 跳过 5s sleep
        import builder.recovery_host as rh
        monkeypatch.setattr(rh.time, "sleep", lambda *a, **k: None)
        rc = cmd_enter(t)
        assert rc == 0
        assert ["recoveryctl", "reboot", "recovery"] in t.shell_calls
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

    def test_flash_pushes_and_invokes_recoveryctl(self, tmp_path, capsys):
        img = tmp_path / "rootfs.img"
        img.write_bytes(b"\x00" * 16)
        t = FakeTransport(mode_sequence=["recovery"])
        rc = cmd_flash(t, partition="rootfs", image=img)
        assert rc == 0
        # push 调用一次
        assert len(t.push_calls) == 1
        local, remote = t.push_calls[0]
        assert local == img
        assert remote.endswith("/rootfs.img")
        # 至少有一条 shell 调用是 recoveryctl flash
        flash_calls = [c for c in t.shell_calls
                       if c and c[0:2] == ["recoveryctl", "flash"]]
        assert len(flash_calls) == 1
        # sha256 参数附带
        assert "--sha256" in flash_calls[0]


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
    def test_backup_pulls_remote(self, tmp_path):
        out = tmp_path / "rootfs-backup.img.zst"
        t = FakeTransport(mode_sequence=["recovery"])
        rc = cmd_backup(t, partition="rootfs", output=out)
        assert rc == 0
        # 远端 backup 命令调用
        backup_calls = [c for c in t.shell_calls if c[0:2] == ["recoveryctl", "backup"]]
        assert len(backup_calls) == 1
        assert "--compress" in backup_calls[0]
        # pull 调用一次
        assert len(t.pull_calls) == 1
        assert t.pull_calls[0][1] == out
        # 文件已落盘
        assert out.exists()

    def test_backup_in_normal_mode_rejected(self, tmp_path):
        t = FakeTransport(mode_sequence=["normal"])
        with pytest.raises(HostRecoveryError, match="recovery enter"):
            cmd_backup(t, partition="rootfs", output=tmp_path / "x")


# ── reboot ──────────────────────────────────────────────────


class TestReboot:
    def test_reboot_invalid_target(self):
        t = FakeTransport()
        with pytest.raises(HostRecoveryError, match="normal 或 recovery"):
            cmd_reboot(t, target="garbage")

    def test_reboot_normal(self):
        t = FakeTransport()
        rc = cmd_reboot(t, target="normal")
        assert rc == 0
        assert ["recoveryctl", "reboot", "normal"] in t.shell_calls
