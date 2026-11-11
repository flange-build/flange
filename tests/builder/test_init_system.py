"""init 命令生成、OpenRC 实际进程识别与部署入口选择。"""

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from builder import deploy
from builder.app_build import AppBuilder
from builder.app_spec import AppInfo, AppSpec, MaintainerInfo, OpenrcConfig, SystemdConfig
from builder.distro import AptDistro
from builder.init_system import OPENRC, SYSTEMD, InitSystemError, get_init_system


def test_systemd_commands_address_requested_unit():
    assert SYSTEMD.reload() == ["systemctl", "daemon-reload"]
    assert SYSTEMD.restart("a.service") == ["systemctl", "restart", "a.service"]
    assert SYSTEMD.is_active("a.service") == ["systemctl", "is-active", "--quiet", "a.service"]
    assert SYSTEMD.main_pid("a.service") == [
        "systemctl", "show", "a.service", "--property", "MainPID", "--value"]
    assert SYSTEMD.log("a.service", lines=5, since="1h", follow=True) == [
        "journalctl", "-u", "a.service", "--no-pager", "-n", "5", "--since", "1h", "-f"]


def test_openrc_commands_follow_flange_conventions():
    assert OPENRC.reload() is None
    assert OPENRC.restart("demo") == ["rc-service", "demo", "restart"]
    assert OPENRC.is_active("demo") == ["rc-service", "--quiet", "demo", "status"]
    assert OPENRC.log("demo") == ["tail", "-n", "+1", "/var/log/demo.log"]
    assert OPENRC.log("demo", lines=20, follow=True) == [
        "tail", "-n", "20", "-F", "/var/log/demo.log"]
    with pytest.raises(InitSystemError, match="--since"):
        OPENRC.log("demo", since="1h")


@pytest.fixture
def openrc_process(tmp_path, monkeypatch):
    """用临时 PID 文件替代 /run，进程存活和父子关系由真实 /proc 校验。"""
    commands = tmp_path / "bin"
    commands.mkdir()
    scripts = {
        "cat": 'case "$1" in /run/*) exec /bin/cat "$FLANGE_TEST_ROOT$1";; '
               '*) exec /bin/cat "$@";; esac\n',
        "readlink": 'if [ "$1" = "/proc/$FLANGE_TEST_SUPERVISOR/exe" ]; then\n'
                    '    printf "%s\\n" /sbin/supervise-daemon\n'
                    'else\n    exec /usr/bin/readlink "$@"\nfi\n',
    }
    for name, script in scripts.items():
        command = commands / name
        command.write_text("#!/bin/bash\nset -xeuo pipefail\n" + script)
        command.chmod(0o755)
    monkeypatch.setenv("PATH", f"{commands}:{os.environ['PATH']}")
    monkeypatch.setenv("FLANGE_TEST_ROOT", str(tmp_path))
    monkeypatch.setenv("FLANGE_TEST_SUPERVISOR", str(os.getpid()))
    monkeypatch.setenv("RC_SVCDIR", "/run/openrc")
    pid_file = tmp_path / "run/demo.pid"
    child_file = tmp_path / "run/openrc/options/demo/child_pid"
    child_file.parent.mkdir(parents=True)
    with subprocess.Popen(["sleep", "30"]) as child:
        try:
            yield pid_file, child_file, child.pid
        finally:
            child.terminate()
            child.wait(timeout=5)


@pytest.mark.parametrize("supervised", [False, True])
def test_openrc_pid_command_returns_service_process(openrc_process, supervised):
    pid_file, child_file, child_pid = openrc_process
    pid_file.write_text(str(os.getpid() if supervised else child_pid))
    child_file.write_text(str(child_pid))

    result = subprocess.run(OPENRC.main_pid("demo"), capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert result.stdout == f"{child_pid}\n"


@pytest.mark.parametrize("invalid", ["", "0", "-1", "not-a-pid", "missing-child", "wrong-parent"])
def test_openrc_pid_command_rejects_invalid_identity(openrc_process, invalid):
    pid_file, child_file, _ = openrc_process
    pid_file.write_text(str(os.getpid()) if invalid in {"missing-child", "wrong-parent"}
                        else invalid)
    if invalid == "wrong-parent":
        child_file.write_text(str(os.getpid()))

    result = subprocess.run(OPENRC.main_pid("demo"), capture_output=True, text=True)

    assert result.returncode != 0
    assert result.stdout == ""


def test_unknown_init_system_is_rejected():
    with pytest.raises(InitSystemError, match="runit"):
        get_init_system("runit")


def test_apt_distro_defaults_to_systemd_and_deb():
    assert AptDistro.init_system == "systemd"
    assert AptDistro.package_format == "deb"


def _report(identity: dict):
    root = SimpleNamespace(app_type="service", service_unit="demo", executable="")
    return SimpleNamespace(userland_identity=identity, root=lambda: root)


def test_deploy_uses_report_init_system():
    assert deploy._runtime_command(_report({"init_system": "openrc"}), []) == [
        "rc-service", "demo", "restart"]
    assert deploy._runtime_command(_report({}), []) == ["systemctl", "restart", "demo"]


def _service_spec(*, systemd=None, openrc=None) -> AppSpec:
    return AppSpec(
        app=AppInfo(name="demo", version="1.0", description="d", type="service", arch=["armhf"]),
        maintainer=MaintainerInfo(name="flange", email="flange@localhost"),
        systemd=systemd,
        openrc=openrc,
    )


def test_openrc_target_requires_executable_init_script():
    spec = _service_spec(openrc=OpenrcConfig(script="openrc/demo"))
    files = [(Path("x"), "/etc/init.d/demo", 0o755)]

    assert AppBuilder._runtime_for(spec, files, "openrc") == ("", "demo")
    with pytest.raises(ValueError, match="不可执行"):
        AppBuilder._runtime_for(spec, [(Path("x"), "/etc/init.d/demo", 0o644)], "openrc")


def test_systemd_only_app_is_rejected_on_openrc_target():
    spec = _service_spec(systemd=SystemdConfig(unit="systemd/demo.service"))

    with pytest.raises(ValueError, match="openrc.script"):
        AppBuilder._runtime_for(spec, [], "openrc")


def test_openrc_only_app_is_rejected_on_systemd_target():
    spec = _service_spec(openrc=OpenrcConfig(script="openrc/demo"))

    with pytest.raises(ValueError, match="systemd.unit"):
        AppBuilder._runtime_for(spec, [], "systemd")
