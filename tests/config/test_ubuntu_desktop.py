"""Ubuntu Desktop 通用 package 配置测试。"""

import importlib.util
import json
from importlib.machinery import SourceFileLoader
from unittest.mock import MagicMock

import pytest

from builder.app import collect_files
from builder.app_spec import load_spec
from builder.config.registry import discover_boards, resolve_config
from builder.paths import PROJECT_ROOT
from builder.platforms.rockchip.rootfs import RockchipRootfsBuilder


DESKTOP_PACKAGES = {
    "ubuntu-desktop",
    "glmark2-wayland",
    "language-pack-zh-hans",
    "language-pack-gnome-zh-hans",
    "fonts-noto-cjk",
    "gnome-remote-desktop",
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
    assert desktop["rootfs"]["gnome_remote_desktop_login"] is True
    assert package_config in desktop.jsonnet_dependencies

    assert DESKTOP_PACKAGES.isdisjoint(default["rootfs"]["packages"])
    assert "flange-ubuntu-desktop-config" not in (
        default["rootfs"].get("custom_packages") or []
    )
    assert _rootfs_partition(default)["image_size"] == "2G"
    assert default["rootfs"]["gnome_remote_desktop_login"] is False
    assert package_config not in default.jsonnet_dependencies


def test_desktop_vendor_app_carries_locale_and_chromium_unit():
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
    assert "/etc/default/locale" in install_paths
    assert (
        "/lib/systemd/system/flange-configure-ubuntu-desktop.service"
        in install_paths
    )
    assert (
        "/usr/lib/flange-ubuntu-desktop-config/"
        "flange-configure-ubuntu-desktop"
        in install_paths
    )
    assert (package_dir / "conf/locale").read_text() == (
        "LANG=zh_CN.UTF-8\nLANGUAGE=zh_CN:zh\n"
    )
    unit = (
        package_dir
        / "systemd/flange-configure-ubuntu-desktop.service"
    ).read_text()
    assert "gnome-remote-desktop-login.json" in unit
    assert "display-manager.service" in unit
    assert "ConditionPathExists=|!/snap/bin/chromium" in unit


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
    module.CHROMIUM_PATH = tmp_path / "chromium"
    calls = []
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda args, check: calls.append((tuple(args), check)),
    )

    module.main()

    assert not credentials.exists()
    commands = [args for args, check in calls if check]
    assert any(
        command[-3:] == (
            "set-credentials", "alice", "复杂 密码$1"
        )
        for command in commands
    )
    assert any(command[-1] == "enable" for command in commands)
    assert (
        "/usr/bin/systemctl", "enable", "gnome-remote-desktop.service",
    ) in commands
    assert (
        "/usr/bin/systemctl", "restart", "gnome-remote-desktop.service",
    ) in commands
    assert commands[-1] == ("/usr/bin/snap", "install", "chromium")


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
            assert _rootfs_partition(config)["image_size"] == "6G"

    assert "desktop" not in boards["atk-rk3506b"]["products"]
