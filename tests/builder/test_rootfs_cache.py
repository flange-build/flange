"""rootfs 基础计划与两阶段编排：执行输入与快照身份使用同一契约。"""

from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from builder.apt import AptCache
from builder.platforms.rockchip.rootfs import RockchipRootfsBuilder
from builder.rootfs_base import apt_command, base_plan
from tests.builder.context import component_context


def _config():
    return {
        "board": "test",
        "product": "default",
        "variant": "release",
        "architecture": {"userspace": "aarch64", "kernel": "arm64", "bootloader": "arm"},
        "rootfs": {
            "url": "https://example.test/base.tar.gz",
            "sha256": "a" * 64,
            "packages": ["systemd"],
            "custom_packages": [],
            "install_recommends": False,
        },
    }


def _builder(tmp_path, config=None):
    builder = RockchipRootfsBuilder(MagicMock(), MagicMock())
    builder.context = component_context(tmp_path, config or _config())
    return builder


def test_base_path_requires_context():
    builder = RockchipRootfsBuilder(MagicMock(), MagicMock())
    with pytest.raises(RuntimeError, match="WorkspaceContext"):
        builder._get_base_cache_path(_config())


def test_base_path_does_not_require_component_cache(tmp_path):
    builder = _builder(tmp_path)
    assert builder.cache is None
    path = builder._get_base_cache_path(_config())
    assert path.parent == tmp_path / ".build/cache/rootfs-base"
    assert path.name.startswith("base-") and path.name.endswith(".tar.zst")


@pytest.mark.parametrize("changed", ["variant", "board", "product"])
def test_equal_base_inputs_share_path_across_targets(tmp_path, changed):
    config = _config()
    other = deepcopy(config)
    other[changed] = "other"
    assert _builder(tmp_path, config)._get_base_cache_path(config) == (
        _builder(tmp_path, other)._get_base_cache_path(other)
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("packages", ["systemd", "vim"]),
        ("install_recommends", True),
        ("emulator", "custom-qemu"),
        ("sha256", "b" * 64),
        (
            "extra_apt_sources",
            [
                {
                    "name": "demo",
                    "source": "deb example noble main",
                    "key": {"url": "https://example.test/key", "sha256": "c" * 64},
                }
            ],
        ),
    ],
)
def test_consumed_input_changes_snapshot_identity(tmp_path, field, value):
    config = _config()
    other = deepcopy(config)
    other["rootfs"][field] = value
    builder = _builder(tmp_path)
    assert builder._get_base_cache_path(config) != builder._get_base_cache_path(other)


def test_phase2_configuration_does_not_change_base_identity(tmp_path):
    config = _config()
    other = deepcopy(config)
    other["rootfs"].update(
        custom_packages=["demo"],
        hostname="another",
        users={"user": {}},
        phase2_packages=["nvidia-l4t-core=32.7.6-20241104234601"],
    )
    builder = _builder(tmp_path)
    assert builder._get_base_cache_path(config) == builder._get_base_cache_path(other)


def test_phase2_packages_install_after_extra_debs_before_modules(tmp_path):
    builder = _builder(tmp_path)
    calls = []
    for name in (
        "_install_app_debs", "_install_extra_debs", "_install_phase2_packages",
        "_install_kernel_modules", "_install_kernel_headers", "_install_extra_firmware",
        "_install_panel_firmware", "apply_overlays", "_configure_default_locale",
        "_configure_users", "_install_hostname", "_export_package_manifest",
    ):
        setattr(builder, name, lambda *args, _name=name: calls.append(_name))

    builder._build_phase2(tmp_path, _config())

    assert calls.index("_install_extra_debs") < calls.index("_install_phase2_packages")
    assert calls.index("_install_phase2_packages") < calls.index("_install_kernel_modules")


def test_empty_phase2_packages_touch_nothing(tmp_path, monkeypatch):
    chroot = MagicMock()
    monkeypatch.setattr("builder.rootfs.ChrootContext", chroot)

    _builder(tmp_path)._install_phase2_packages(tmp_path, _config())

    chroot.assert_not_called()


def test_phase2_packages_refresh_index_and_use_recommendation_policy(tmp_path, monkeypatch):
    chroot = MagicMock()
    session = chroot.return_value.__enter__.return_value
    monkeypatch.setattr("builder.rootfs.ChrootContext", chroot)
    config = _config()
    config["rootfs"]["phase2_packages"] = ["nvidia-l4t-core=32.7.6-20241104234601"]

    _builder(tmp_path, config)._install_phase2_packages(tmp_path, config)

    commands = [call.args[0] for call in session.run.call_args_list]
    assert commands == [
        ["apt-get", "update"],
        ["apt-get", "install", "-y", "--no-install-recommends",
         "nvidia-l4t-core=32.7.6-20241104234601"],
        ["apt-get", "clean"],
    ]
    mount_source, mount_target = session.bind_mount.call_args.args
    assert mount_source == str(AptCache(tmp_path / ".build/cache/apt").archives)
    assert mount_target == tmp_path / "var/cache/apt/archives"


def test_plan_apt_command_consumes_same_recommendation_policy(tmp_path):
    config = _config()
    context = component_context(tmp_path, config)
    plan = base_plan(config, "rootfs", context)
    assert apt_command(plan.value("apt")) == [
        "apt-get",
        "install",
        "-y",
        "--no-install-recommends",
        "systemd",
    ]
    config["rootfs"]["install_recommends"] = True
    enabled = base_plan(config, "rootfs", context)
    assert "--no-install-recommends" not in apt_command(enabled.value("apt"))


@pytest.mark.parametrize("hit", [False, True])
def test_compile_uses_verified_restore_result_and_always_customizes(tmp_path, hit):
    builder = _builder(tmp_path)
    calls = []
    builder._extract_base = MagicMock(return_value=hit)
    builder._build_phase1 = MagicMock(side_effect=lambda *args: calls.append("base"))
    builder._save_base_snapshot = MagicMock(side_effect=lambda *args: calls.append("save"))
    builder._build_phase2 = MagicMock(side_effect=lambda *args: calls.append("customize"))
    builder._post_customize = MagicMock()
    builder._install_fstab = MagicMock()
    builder._ensure_api_mountpoints = MagicMock()
    builder._build_image = MagicMock(side_effect=lambda *args: calls.append("image"))
    builder.compile(None, _config())
    assert calls == (["customize", "image"] if hit else ["base", "save", "customize", "image"])
    assert builder._phase1_plan.value("apt")["packages"] == ["systemd"]
