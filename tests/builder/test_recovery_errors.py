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


class FakeTransport(Transport):
    def __init__(self, *, mode: str = "recovery"):
        self.mode = mode
        self.shell_calls: list[list[str]] = []
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

    def test_uppercase_yes_proceeds(self, tmp_path):
        img = tmp_path / "raw.img"
        img.write_bytes(b"\x00" * 8)
        t = FakeTransport()
        rc = cmd_flash(t, partition="rootfs", image=img, force=True,
                       prompt=lambda *_: "YES")
        assert rc == 0
        # --force 应被透传到 recoveryctl
        flash_calls = [c for c in t.shell_calls
                       if c and c[0:2] == ["recoveryctl", "flash"]]
        assert any("--force" in c for c in flash_calls)

    def test_no_prompt_without_force(self, tmp_path):
        """非 force 路径不应触发 prompt。"""
        img = tmp_path / "raw.img"
        img.write_bytes(b"\x00" * 8)
        t = FakeTransport()
        prompt_calls = []
        rc = cmd_flash(
            t, partition="rootfs", image=img, force=False,
            prompt=lambda *args: prompt_calls.append(args) or "no",
        )
        assert rc == 0
        assert prompt_calls == []


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

    def test_force_protected_without_sha_raises(self, rc, tmp_path):
        img = tmp_path / "rec.img"
        img.write_bytes(b"\x00" * 16)
        req = rc.FlashRequest(
            partition="recovery", image_path=img,
            sha256_expected=None, force=True,
        )
        with pytest.raises(rc.RecoveryError, match="--sha256"):
            rc.validate_flash(
                req, self._config(),
                block_size_lookup=lambda d: 1 << 30,
                mounted_lookup=lambda d: None,
                partition_resolver=lambda n: Path(f"/dev/{n}"),
            )

    def test_force_protected_with_sha_passes(self, rc, tmp_path):
        img = tmp_path / "rec.img"
        img.write_bytes(b"\x00" * 16)
        digest = rc.sha256_of_file(img)
        req = rc.FlashRequest(
            partition="recovery", image_path=img,
            sha256_expected=digest, force=True,
        )
        dev = rc.validate_flash(
            req, self._config(),
            block_size_lookup=lambda d: 1 << 30,
            mounted_lookup=lambda d: None,
            partition_resolver=lambda n: Path(f"/dev/{n}"),
        )
        assert dev == Path("/dev/recovery")

    def test_unprotected_partition_unaffected(self, rc, tmp_path):
        """rootfs 不是 protected，--force 也不强制要求 --sha256。"""
        img = tmp_path / "rfs.img"
        img.write_bytes(b"\x00" * 16)
        req = rc.FlashRequest(
            partition="rootfs", image_path=img,
            sha256_expected=None, force=True,
        )
        dev = rc.validate_flash(
            req, self._config(),
            block_size_lookup=lambda d: 1 << 30,
            mounted_lookup=lambda d: None,
            partition_resolver=lambda n: Path(f"/dev/{n}"),
        )
        assert dev == Path("/dev/rootfs")


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
    def test_image_too_large_for_protected_partition(self, rc, tmp_path):
        img = tmp_path / "big.img"
        img.write_bytes(b"\x00" * 1024)
        digest = rc.sha256_of_file(img)
        req = rc.FlashRequest(
            partition="recovery", image_path=img,
            sha256_expected=digest, force=True,
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

    def test_already_mounted_with_force(self, rc, tmp_path):
        """挂载检查不被 --force 跳过。"""
        img = tmp_path / "x.img"
        img.write_bytes(b"\x00" * 16)
        digest = rc.sha256_of_file(img)
        req = rc.FlashRequest(
            partition="recovery", image_path=img,
            sha256_expected=digest, force=True,
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
