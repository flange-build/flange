"""usbmoded 能力 daemon 的服务管理后端：systemd 不变，OpenRC 翻译为 rc-service。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "components/app/usbmoded"))

from usbmoded.capabilities import daemon  # noqa: E402


@pytest.fixture
def calls(monkeypatch):
    recorded = []

    def fake_run(cmd, **kwargs):
        recorded.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="x.service enabled\n", stderr="")

    monkeypatch.setattr(daemon.subprocess, "run", fake_run)
    return recorded


def _use(monkeypatch, tmp_path, init: str):
    runtime = tmp_path / "run-systemd"
    if init == "systemd":
        runtime.mkdir()
    monkeypatch.setattr(daemon, "SYSTEMD_RUNTIME", str(runtime))
    monkeypatch.setattr(daemon, "OPENRC_INIT_DIR", str(tmp_path / "init.d"))


def test_systemd_commands_unchanged(monkeypatch, tmp_path, calls):
    _use(monkeypatch, tmp_path, "systemd")

    daemon.start("adbd")
    daemon.stop("adbd")
    daemon.restart("adbd")
    assert daemon.is_active("adbd")
    assert daemon.exists("adbd")

    assert calls == [
        ["systemctl", "start", "usbmoded-adbd.service"],
        ["systemctl", "stop", "usbmoded-adbd.service"],
        ["systemctl", "restart", "usbmoded-adbd.service"],
        ["systemctl", "is-active", "--quiet", "usbmoded-adbd.service"],
        ["systemctl", "list-unit-files", "--no-legend", "usbmoded-adbd.service"],
    ]


def test_openrc_commands(monkeypatch, tmp_path, calls):
    _use(monkeypatch, tmp_path, "openrc")
    (tmp_path / "init.d").mkdir()

    assert not daemon.exists("adbd")
    (tmp_path / "init.d/usbmoded-adbd").write_text("#!/sbin/openrc-run\n")
    assert daemon.exists("adbd")
    daemon.start("adbd")
    daemon.restart("adbd")
    assert daemon.is_active("adbd")
    daemon.stop("adbd")

    assert daemon.unit_name("adbd") == "usbmoded-adbd"
    assert calls == [
        ["rc-service", "--quiet", "usbmoded-adbd", "start"],
        ["rc-service", "--quiet", "usbmoded-adbd", "restart"],
        ["rc-service", "--quiet", "usbmoded-adbd", "status"],
        ["rc-service", "--quiet", "usbmoded-adbd", "stop"],
    ]


def test_missing_service_manager_is_reported(monkeypatch, tmp_path):
    _use(monkeypatch, tmp_path, "openrc")

    def missing(cmd, **kwargs):
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(daemon.subprocess, "run", missing)
    with pytest.raises(daemon.DaemonError, match="rc-service 不可用"):
        daemon.start("adbd")
