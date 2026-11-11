"""Recovery 的架构选择、容量校验、应用闭包与独立定制行为。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from builder.docker import BuildError
from builder.packaging.model import PackageArtifact
from builder.recovery import RecoveryBuilder, build_recovery_config
from builder.rootfs import RootfsBuilder
from builder.app_model import AppBuildReport
from tests.builder.context import component_context


def _builder(tmp_path: Path) -> RecoveryBuilder:
    builder = RecoveryBuilder(MagicMock(), MagicMock())
    cache = MagicMock()
    cache.target_dir = tmp_path / "target"
    builder.cache = cache
    builder.output = None
    builder.context = component_context(tmp_path, target_dir=cache.target_dir)
    return builder


def test_recovery_image_uses_recovery_label_size_and_output(tmp_path):
    builder = _builder(tmp_path)
    builder._work_dir = tmp_path
    builder.docker.run.return_value = MagicMock(stdout="24\t/root")
    config = {"partitions": {"entries": [
        {"name": "rootfs", "size": "2G"},
        {"name": "recovery", "size": "64M"},
    ]}}

    builder._build_image(tmp_path / "root", config)

    commands = [call.args[0] for call in builder.docker.run.call_args_list]
    assert ["truncate", "-s", "64M", str(tmp_path / "recovery.img")] in commands
    format_command = next(command for command in commands if command[0] == "mke2fs")
    assert format_command[format_command.index("-L") + 1] == "recovery"
    assert builder.collect(None, config) == {"recovery": tmp_path / "recovery.img"}


# 按目标架构选择 emulator
# ---------------------------------------------------------------------------


def test_emulator按arch推导而不是硬编码aarch64():
    """合并前 recovery 写死 qemu-aarch64-static，armhf 板会拿错 emulator。"""
    builder = RecoveryBuilder(MagicMock(), MagicMock())
    armhf = {"architecture": {"userspace": "armhf"}, "rootfs": {}}
    assert builder._rootfs_emulator(armhf) == "qemu-arm-static"

    aarch64 = {"architecture": {"userspace": "aarch64"}, "rootfs": {}}
    assert builder._rootfs_emulator(aarch64) == "qemu-aarch64-static"


# 镜像容量与分区几何
# ---------------------------------------------------------------------------


def test_recovery分区的image_size生效():
    """合并前 recovery 自己算 int(size,0)*512，声明 image_size 被静默忽略。"""
    builder = RecoveryBuilder(MagicMock(), MagicMock())
    config = {
        "partitions": {
            "entries": [
                # 分区 256MB，但只想做 96MB 的镜像（留给首启动扩容）
                {"name": "recovery", "type": "ext4", "size": "0x80000", "image_size": "96M"},
            ]
        }
    }
    assert builder._partition_size_mb(config, "recovery") == 96


# 镜像容量校验
# ---------------------------------------------------------------------------


def test_门禁按实测ext4开销放行真实的recovery(tmp_path: Path):
    """rock5b 的真实数值，取自实机构建。

    du 449MB 的内容做进 512MiB 镜像后 ext4 实占 461MB（开销 2.7%），剩
    75MB —— 这是一个能正常工作的配置，门禁必须放行。

    初版按 rootfs 的经验取 20% 且下限固定 128MiB，要求 577MB > 512MB，
    把它拦下了。门禁只预测 mke2fs 会不会失败，不承担运行期余量策略。
    """
    builder = _builder(tmp_path)
    builder.docker.run.return_value = MagicMock(stdout="449\t/x")
    builder._ensure_rootfs_fits_image(tmp_path, 512)


def test_门禁在小镜像上依然有效(tmp_path: Path):
    """下限 32MiB 覆盖小镜像的固定 journal 开销，且不至于永远不可能通过。"""
    builder = _builder(tmp_path)
    builder.docker.run.return_value = MagicMock(stdout="24\t/x")
    builder._ensure_rootfs_fits_image(tmp_path, 64)  # 24+32=56 ≤ 64

    builder.docker.run.return_value = MagicMock(stdout="40\t/x")
    with pytest.raises(BuildError):
        builder._ensure_rootfs_fits_image(tmp_path, 64)  # 40+32=72 > 64


def test_装不下时报的是flange的话而不是mke2fs的话(tmp_path: Path):
    from builder.docker import BuildError

    builder = _builder(tmp_path)
    builder.docker.run.return_value = MagicMock(stdout="80\t/x")
    with pytest.raises(BuildError) as exc:
        builder._ensure_rootfs_fits_image(tmp_path, 64)
    assert "recovery" in str(exc.value), "报错要说清是哪个组件装不下"


# Recovery 的应用、配置与 overlay
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "builder_class,component",
    [
        (RecoveryBuilder, "recovery"),
        (RootfsBuilder, "rootfs"),
    ],
)
def test_只装声明的custom_packages及运行依赖(tmp_path: Path, builder_class, component):
    """同份系统报告含多个请求根；每个 rootfs 只安装自己的闭包。"""
    dependency = tmp_path / "shared.deb"
    selected = tmp_path / "recoveryctl-runtime.deb"
    unrelated = tmp_path / "desktop.deb"
    for path in (dependency, selected, unrelated):
        path.write_bytes(b"deb")
    from types import SimpleNamespace

    def result(name, deps, deb):
        return SimpleNamespace(
            resource_id=name,
            name=name,
            dependency_ids=deps,
            runtime_packages=(PackageArtifact(deb, "deb", "runtime"),),
            validate=lambda: True,
        )

    report = AppBuildReport(
        ("recoveryctl", "desktop"),
        (
            result("shared", (), dependency),
            result("recoveryctl", ("shared",), selected),
            result("desktop", (), unrelated),
        ),
        {},
        "aarch64",
    )
    builder = builder_class(MagicMock(), MagicMock())
    builder.app_report = report
    # 本单测隔离清单完整性门禁，真实完整性与 target/ABI 检查由 App 报告测试覆盖。
    with (
        patch.object(AppBuildReport, "validate", return_value=True),
        patch("builder.rootfs.ChrootContext") as chroot,
    ):
        builder._install_app_debs(
            tmp_path / "root", {component: {"custom_packages": ["recoveryctl"]}}
        )
    command = chroot.return_value.__enter__.return_value.run.call_args.args[0]
    assert command[3:] == [
        "/tmp/flange-debs/shared.deb",
        "/tmp/flange-debs/recoveryctl-runtime.deb",
    ]
    assert not any("desktop" in value for value in command)


def test_recovery配置json写进镜像固定路径(tmp_path: Path):
    builder = _builder(tmp_path)
    root = tmp_path / "recovery"
    root.mkdir()
    config = {
        "board": "b",
        "product": "default",
        "variant": "release",
        "recovery": {"transport": "adb", "protected_partitions": ["uboot"]},
        "partitions": {
            "entries": [
                {"name": "uboot", "type": "raw", "offset": "0x4000", "size": "0x4000"},
                {"name": "rootfs", "type": "ext4", "offset": "0x8000", "size": "0x100000"},
            ]
        },
    }
    builder._post_customize(root, config)

    written = json.loads((root / "etc/flange/recovery-config.json").read_text())
    assert written == build_recovery_config(config)
    protection = {p["name"]: p["protected"] for p in written["partitions"]}
    assert protection == {"uboot": True, "rootfs": False}


def test_overlay走独立目录不与normal_rootfs混用(tmp_path: Path, monkeypatch):
    """同一块板要能给救援系统和正常系统不同的配置。"""
    monkeypatch.chdir(tmp_path)
    for relative in (
        "components/recovery/overlay",
        "components/platform/rockchip/recovery-overlay",
        "components/board/b/recovery-overlay",
        "components/rootfs/overlay",
        "components/board/b/overlay",
    ):
        path = tmp_path / relative
        path.mkdir(parents=True)
        (path / "marker").write_text("x")

    builder = _builder(tmp_path)
    builder.apply_overlays(tmp_path / "recovery", {"platform": "rockchip", "board": "b"})

    copied = [str(call.args[0]) for call in builder.docker.run_privileged.call_args_list]
    joined = " ".join(copied)
    assert "components/recovery/overlay" in joined
    assert "components/platform/rockchip/recovery-overlay" in joined
    assert "components/board/b/recovery-overlay" in joined
    assert "components/rootfs/overlay" not in joined, "不该混用 normal overlay"
    assert "components/board/b/overlay/." not in joined


def test_phase2_installs_rescue_contents_without_normal_system_customization(tmp_path):
    """recovery 只走 adb 通道，账号体系与 locale 都没有意义且占空间。"""
    builder = _builder(tmp_path)
    calls = []
    for name in (
        "_install_app_debs", "_install_kernel_modules", "apply_overlays",
        "_export_package_manifest",
    ):
        setattr(builder, name, lambda *args, _name=name: calls.append(_name))
    for name in (
        "_configure_users",
        "_configure_default_locale",
        "_install_extra_firmware",
        "_install_hostname",
    ):
        setattr(builder, name, MagicMock(side_effect=AssertionError(name)))

    builder._build_phase2(tmp_path, {"recovery": {}})

    assert calls == [
        "_install_app_debs", "_install_kernel_modules", "apply_overlays",
        "_export_package_manifest",
    ]


def test_基础快照按实际包输入共享而不是组件名隔离(tmp_path):
    """相同基础输入可复用，差异 APT 集合必须得到不同身份。"""
    recovery = _builder(tmp_path)
    normal = RootfsBuilder(MagicMock(), MagicMock())
    normal.context = recovery.context
    config = {
        "architecture": {"userspace": "aarch64"},
        "rootfs": {"url": "https://example.test/base", "sha256": "a" * 64, "packages": ["systemd"]},
        "recovery": {"packages": ["systemd"]},
    }
    same = recovery._get_base_cache_path(config)
    assert same == normal._get_base_cache_path(config)
    config["recovery"]["packages"] = ["systemd", "rescue"]
    assert recovery._get_base_cache_path(config) != same
