"""init 系统抽象：systemd 命令序列保持不变，OpenRC 按约定生成。"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from builder import deploy
from builder.app_build import AppBuilder
from builder.app_spec import AppInfo, AppSpec, MaintainerInfo, OpenrcConfig, SystemdConfig
from builder.distro import AptDistro
from builder.init_system import OPENRC, SYSTEMD, InitSystemError, get_init_system


def test_systemd_commands_are_unchanged():
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
    assert OPENRC.main_pid("demo") == [
        "sh", "-c", 'p=$(cat /run/demo.pid) && { pgrep -P "$p" || echo "$p"; } | head -n 1']
    assert OPENRC.log("demo") == ["tail", "-n", "+1", "/var/log/demo.log"]
    assert OPENRC.log("demo", lines=20, follow=True) == [
        "tail", "-n", "20", "-F", "/var/log/demo.log"]
    with pytest.raises(InitSystemError, match="--since"):
        OPENRC.log("demo", since="1h")


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
