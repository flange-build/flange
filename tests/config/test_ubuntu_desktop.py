"""Ubuntu Desktop 通用 package 配置测试。"""

import importlib.util
import json
import subprocess
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from builder.app import collect_files
from builder.app_spec import load_spec
from builder.config.registry import discover_boards, resolve_config
from builder.config.validate import ConfigError, validate_canonical_config
from builder.paths import PROJECT_ROOT
from builder.platforms.rockchip.rootfs import RockchipRootfsBuilder


DESKTOP_PACKAGES = {
    "ubuntu-desktop",
    "glmark2-wayland",
    "language-pack-zh-hans",
    "language-pack-gnome-zh-hans",
    "fonts-noto-cjk",
    "gnome-remote-desktop",
    "openssl",
    "chromium-browser",
    "snapd",
}
def _rootfs_partition(config):
    return next(
        entry for entry in config["partitions"]["entries"]
        if entry["name"] == "rootfs"
    )


def test_desktop_product_applies_common_package_config():
    desktop = resolve_config("radxa-zero3w", "desktop", "release")
    default = resolve_config("radxa-zero3w", "default", "release")
    package_config = (
        PROJECT_ROOT / "components/packages/ubuntu-desktop/config.jsonnet"
    )

    assert DESKTOP_PACKAGES <= set(desktop["rootfs"]["packages"])
    assert "flange-ubuntu-desktop-config" in (
        desktop["rootfs"]["custom_packages"]
    )
    assert desktop["external_apps"]["flange-ubuntu-desktop-config"] == {
        "local_path": str(
            PROJECT_ROOT / "components/packages/ubuntu-desktop"
        ),
    }
    assert _rootfs_partition(desktop)["image_size"] == "6G"
    assert desktop["rootfs"]["default_locale"] == {
        "lang": "zh_CN.UTF-8",
        "language": "zh_CN:zh",
    }
    assert desktop["rootfs"]["gnome_remote_desktop_login"] is True
    assert desktop["rootfs"]["install_recommends"] is True
    assert package_config in desktop.jsonnet_dependencies

    assert DESKTOP_PACKAGES.isdisjoint(default["rootfs"]["packages"])
    assert "flange-ubuntu-desktop-config" not in (
        default["rootfs"].get("custom_packages") or []
    )
    assert _rootfs_partition(default)["image_size"] == "2G"
    assert default["rootfs"]["gnome_remote_desktop_login"] is False
    assert default["rootfs"]["install_recommends"] is False
    assert package_config not in default.jsonnet_dependencies


def test_desktop_vendor_app_carries_dock_and_first_boot_unit():
    package_dir = PROJECT_ROOT / "components/packages/ubuntu-desktop"
    spec = load_spec(package_dir)
    install_paths = {
        dest for _, dest, _ in collect_files(package_dir, spec, "aarch64")
    }

    assert spec.app.name == "flange-ubuntu-desktop-config"
    assert spec.app.type == "service"
    assert spec.build.system == "none"
    assert spec.systemd is not None
    assert spec.systemd.auto_start is True
    assert "/etc/default/locale" not in install_paths
    assert (
        "/usr/share/glib-2.0/schemas/"
        "99_flange-ubuntu-dock.gschema.override"
        in install_paths
    )
    assert (
        "/lib/systemd/system/flange-configure-ubuntu-desktop.service"
        in install_paths
    )
    assert (
        "/usr/lib/flange-ubuntu-desktop-config/"
        "flange-configure-ubuntu-desktop"
        in install_paths
    )
    assert (
        package_dir
        / "schemas/99_flange-ubuntu-dock.gschema.override"
    ).read_text() == (
        "# Ubuntu desktop profile 的 Dock 默认布局；"
        "用户仍可在 Settings 中覆盖。\n"
        "[org.gnome.shell.extensions.dash-to-dock:ubuntu]\n"
        "dock-position='BOTTOM'\n"
        "dock-fixed=false\n"
        "autohide=true\n"
        "intellihide=true\n"
        "extend-height=false\n"
    )
    unit = (
        package_dir
        / "systemd/flange-configure-ubuntu-desktop.service"
    ).read_text()
    assert "gnome-remote-desktop-login.json" in unit
    assert "display-manager.service" in unit
    assert "ConditionPathExists=|!/snap/bin/chromium" in unit
    assert "ConditionPathExists=|!/snap/bin/snap-store" in unit
    assert "ConditionPathExists=|!/snap/bin/thunderbird" in unit
    assert "rdp-tls.crt" in unit
    assert "rdp-tls.key" in unit


def test_default_locale_writes_systemd_and_debian_paths(tmp_path):
    builder = RockchipRootfsBuilder(MagicMock(), MagicMock())
    locale_conf = tmp_path / "etc/locale.conf"
    locale_conf.parent.mkdir(parents=True)
    locale_conf.write_text("LANG=C.UTF-8\n")
    outside = tmp_path / "outside-locale"
    outside.write_text("unchanged\n")
    default_locale = tmp_path / "etc/default/locale"
    default_locale.parent.mkdir(parents=True)
    default_locale.symlink_to(outside)

    builder._configure_default_locale(tmp_path, {
        "rootfs": {
            "default_locale": {
                "lang": "zh_CN.UTF-8",
                "language": "zh_CN:zh",
            },
        },
    })

    expected = "LANG=zh_CN.UTF-8\nLANGUAGE=zh_CN:zh\n"
    assert locale_conf.read_text() == expected
    assert default_locale.read_text() == expected
    assert default_locale.is_symlink()
    assert default_locale.readlink() == Path("../locale.conf")
    assert outside.read_text() == "unchanged\n"


@pytest.mark.parametrize("default_locale", [
    "zh_CN.UTF-8",
    {"lang": "zh_CN.UTF-8"},
    {"lang": "zh_CN.UTF-8", "language": "zh_CN:zh\nLANG=C"},
])
def test_invalid_default_locale_is_rejected(default_locale):
    config = resolve_config("radxa-zero3w", "desktop", "release")
    config["rootfs"]["default_locale"] = default_locale

    with pytest.raises(ConfigError, match="rootfs.default_locale"):
        validate_canonical_config(config)


def test_install_recommends_switch_controls_apt_command():
    packages = ["ubuntu-desktop"]
    disabled = RockchipRootfsBuilder._apt_install_command(
        packages, {"rootfs": {"install_recommends": False}}
    )
    enabled = RockchipRootfsBuilder._apt_install_command(
        packages, {"rootfs": {"install_recommends": True}}
    )

    assert "--no-install-recommends" in disabled
    assert "--no-install-recommends" not in enabled


def test_invalid_install_recommends_is_rejected():
    config = resolve_config("radxa-zero3w", "desktop", "release")
    config["rootfs"]["install_recommends"] = "yes"

    with pytest.raises(ConfigError, match="rootfs.install_recommends"):
        validate_canonical_config(config)


def test_remote_login_credentials_use_configured_default_user(tmp_path):
    builder = RockchipRootfsBuilder(MagicMock(), MagicMock())
    rootfs_cfg = {
        "default_user": "alice",
        "users": {"alice": {"password": "复杂 密码$1"}},
        "gnome_remote_desktop_login": True,
    }

    builder._validate_account_config(rootfs_cfg)
    builder._write_gnome_remote_desktop_credentials(tmp_path, rootfs_cfg)

    path = (
        tmp_path / "var/lib/flange/gnome-remote-desktop-login.json"
    )
    assert json.loads(path.read_text()) == {
        "username": "alice",
        "password": "复杂 密码$1",
    }
    assert path.stat().st_mode & 0o777 == 0o600


def test_remote_login_rejects_default_user_without_password():
    builder = RockchipRootfsBuilder(MagicMock(), MagicMock())
    with pytest.raises(ValueError, match="password 必须是非空字符串"):
        builder._validate_account_config({
            "default_user": "alice",
            "users": {"alice": {}},
            "gnome_remote_desktop_login": True,
        })


def test_first_boot_script_configures_system_rdp_and_removes_credentials(
    tmp_path, monkeypatch
):
    script = (
        PROJECT_ROOT / "components/packages/ubuntu-desktop/scripts"
        / "flange-configure-ubuntu-desktop"
    )
    loader = SourceFileLoader("flange_desktop_setup", str(script))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)

    credentials = tmp_path / "credentials.json"
    credentials.write_text(json.dumps({
        "username": "alice",
        "password": "复杂 密码$1",
    }))
    module.CREDENTIALS_PATH = credentials
    module.TLS_DIR = tmp_path / "tls"
    module.TLS_CERT_PATH = module.TLS_DIR / "rdp-tls.crt"
    module.TLS_KEY_PATH = module.TLS_DIR / "rdp-tls.key"
    module.SNAP_APPS = (
        (tmp_path / "chromium", ("chromium",)),
        (tmp_path / "snap-store", ("snap-store", "--channel=2/stable")),
        (tmp_path / "thunderbird", ("thunderbird",)),
    )
    calls = []

    def fake_run(args, check):
        calls.append((tuple(args), check))
        if args[0] == "/usr/bin/openssl":
            module.TLS_CERT_PATH.write_text("certificate")
            module.TLS_KEY_PATH.write_text("private key")

    monkeypatch.setattr(
        module.subprocess,
        "run",
        fake_run,
    )
    monkeypatch.setattr(module.shutil, "chown", lambda *args, **kwargs: None)
    monkeypatch.setattr(module.socket, "gethostname", lambda: "test-board")

    module.main()

    assert not credentials.exists()
    assert module.TLS_CERT_PATH.stat().st_mode & 0o777 == 0o644
    assert module.TLS_KEY_PATH.stat().st_mode & 0o777 == 0o600
    commands = [args for args, check in calls if check]
    rdp = ("/usr/bin/grdctl", "--system", "rdp")
    assert rdp + (
        "set-tls-cert", str(module.TLS_CERT_PATH),
    ) in commands
    assert rdp + (
        "set-tls-key", str(module.TLS_KEY_PATH),
    ) in commands
    assert rdp + (
        "set-credentials", "alice", "复杂 密码$1",
    ) in commands
    assert rdp + ("enable",) in commands
    assert (
        "/usr/bin/systemctl", "enable", "gnome-remote-desktop.service",
    ) in commands
    assert (
        "/usr/bin/systemctl", "restart", "gnome-remote-desktop.service",
    ) in commands
    assert commands[-3:] == [
        ("/usr/bin/snap", "install", "chromium"),
        (
            "/usr/bin/snap", "install", "snap-store",
            "--channel=2/stable",
        ),
        ("/usr/bin/snap", "install", "thunderbird"),
    ]

    calls.clear()
    module._configure_remote_login()
    retry_commands = [args for args, check in calls if check]
    assert not any(command[0] == "/usr/bin/openssl"
                   for command in retry_commands)
    assert rdp + (
        "set-tls-cert", str(module.TLS_CERT_PATH),
    ) in retry_commands
    assert not any("set-credentials" in command
                   for command in retry_commands)


def test_remote_login_failure_keeps_staged_credentials(tmp_path, monkeypatch):
    script = (
        PROJECT_ROOT / "components/packages/ubuntu-desktop/scripts"
        / "flange-configure-ubuntu-desktop"
    )
    loader = SourceFileLoader("flange_desktop_setup_retry", str(script))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)

    credentials = tmp_path / "credentials.json"
    credentials.write_text(json.dumps({
        "username": "alice",
        "password": "secret",
    }))
    module.CREDENTIALS_PATH = credentials
    module.TLS_DIR = tmp_path / "tls"
    module.TLS_CERT_PATH = module.TLS_DIR / "rdp-tls.crt"
    module.TLS_KEY_PATH = module.TLS_DIR / "rdp-tls.key"
    def fail_run(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "openssl")

    monkeypatch.setattr(module.subprocess, "run", fail_run)

    with pytest.raises(subprocess.CalledProcessError):
        module._configure_remote_login()

    assert credentials.exists()


def test_all_supported_boards_resolve_desktop_products():
    boards = discover_boards()
    desktop_boards = {
        name for name, identity in boards.items()
        if "desktop" in identity["products"]
    }

    assert len(desktop_boards) == 17
    for board in desktop_boards:
        for variant in ("debug", "release"):
            config = resolve_config(board, "desktop", variant, boards=boards)
            assert DESKTOP_PACKAGES <= set(config["rootfs"]["packages"])
            assert config["rootfs"]["install_recommends"] is True
            assert _rootfs_partition(config)["image_size"] == "6G"

    assert "desktop" not in boards["atk-rk3506b"]["products"]
