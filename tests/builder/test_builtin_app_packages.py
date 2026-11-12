"""仓库内 App 的实际 DEB 产物、安装闭包与构建引擎清单集成。

预编译程序与脚本通过真实 AppBuilder 打包；Docker 调用隔离，未执行目标程序。
通用 DEB 格式和字段生成由 test_deb.py 覆盖。
"""

from __future__ import annotations

import io
import shutil
import tarfile
from pathlib import Path
from typing import Dict
from unittest.mock import MagicMock

import pytest

from builder.app import AppBuilder
from builder.config.registry import resolve_config
from builder.engine import BuildEngine
from builder.source import SourceManager
from builder.workspace import WorkspaceContext, Target

_PROJECT_ROOT = Path(__file__).resolve().parents[2]



def _read_ar_members(deb_path: Path) -> Dict[str, bytes]:
    """从 .deb 文件（ar 格式）读取所有成员，返回 {成员名: 数据} 字典。

    只支持标准 POSIX ar 格式，与 .deb 规范一致。
    """
    data = deb_path.read_bytes()
    magic = b"!<arch>\n"
    if not data.startswith(magic):
        raise ValueError(f"不是有效的 ar 归档：{deb_path}")

    members: Dict[str, bytes] = {}
    pos = len(magic)
    while pos < len(data):
        if pos + 60 > len(data):
            break
        # 解析 60 字节成员头
        header = data[pos: pos + 60]
        name = header[0:16].rstrip().decode("ascii")
        size = int(header[48:58].rstrip())
        end_mag = header[58:60]
        assert end_mag == b"\x60\x0a", f"ar 成员头 magic 错误：{end_mag!r}"

        pos += 60
        member_data = data[pos: pos + size]
        members[name] = member_data
        # 成员数据按 2 字节对齐
        pos += size + (size % 2)

    return members


def _read_tar_names(tar_data: bytes) -> list[str]:
    """从 tar.gz 字节读取所有成员名称列表。"""
    with tarfile.open(fileobj=io.BytesIO(tar_data), mode="r:gz") as tf:
        return tf.getnames()


def _read_tar_member(tar_data: bytes, name: str) -> bytes:
    """从 tar.gz 字节中提取指定成员的内容。"""
    with tarfile.open(fileobj=io.BytesIO(tar_data), mode="r:gz") as tf:
        member = tf.getmember(name)
        f = tf.extractfile(member)
        return f.read() if f else b""


def _get_tar_info(tar_data: bytes, name: str) -> tarfile.TarInfo:
    """从 tar.gz 字节中获取指定成员的 TarInfo（含权限等元数据）。"""
    with tarfile.open(fileobj=io.BytesIO(tar_data), mode="r:gz") as tf:
        return tf.getmember(name)


def test_q8b_firmware_package_builds_flange_deb(tmp_path: Path):
    """package 固件应由 flange 重打 deb，并保留目标路径与原始内容。"""
    config = resolve_config("radxa-dragon-q8b", "default", "release")
    source = SourceManager(
        sources_dir=tmp_path / "sources",
        project_root=_PROJECT_ROOT,
    )
    builder = AppBuilder(
        docker=MagicMock(),
        source=source,
        config=config,
        context=WorkspaceContext(_PROJECT_ROOT, tmp_path, tmp_path / "build",
                                 Target(config["board"], config["product"], config["variant"])),
    )

    deb_path = builder.build_one("firmware-qcom-audioreach").root().runtime_debs[0]

    assert deb_path.name == "firmware-qcom-audioreach_1.0.4-2_arm64.deb"
    members = _read_ar_members(deb_path)
    control = _read_tar_member(
        members["control.tar.gz"], "./control"
    ).decode("utf-8")
    assert "Package: firmware-qcom-audioreach" in control
    assert "Depends:" not in control
    firmware_member = (
        "./lib/firmware/qcom/sc8280xp/"
        "SC8280XP-Radxa-Dragon-Q8B-tplg.bin"
    )
    assert firmware_member in _read_tar_names(members["data.tar.gz"])
    source_blob = (
        _PROJECT_ROOT / "components/packages/firmware-qcom-audioreach/"
        "firmware/qcom/sc8280xp/SC8280XP-Radxa-Dragon-Q8B-tplg.bin"
    )
    assert _read_tar_member(
        members["data.tar.gz"], firmware_member
    ) == source_blob.read_bytes()


def test_q8b_fastrpc_packages_follow_radxa_boundaries(tmp_path: Path):
    """FastRPC 参考 payload 应按 Radxa 包边界重打为 flange deb。"""
    config = resolve_config("radxa-dragon-q8b", "default", "release")
    source = SourceManager(
        sources_dir=tmp_path / "sources",
        project_root=_PROJECT_ROOT,
    )
    builder = AppBuilder(
        docker=MagicMock(),
        source=source,
        config=config,
        context=WorkspaceContext(_PROJECT_ROOT, tmp_path, tmp_path / "build",
                                 Target(config["board"], config["product"], config["variant"])),
    )

    # 只构建本用例验收的 FastRPC 资源闭包；其他 App 的编译与安装各有独立验证。
    requests = ["radxa-firmware-sc8280xp", "libadsprpc1", "libadsp-default-listener1",
                "libcdsprpc1", "libcdsp-default-listener1", "fastrpc"]
    packages = {item.name: item.runtime_debs[0] for item in builder.build(requests).ordered
                if item.runtime_debs}

    assert {
        "radxa-firmware-sc8280xp",
        "libadsprpc1",
        "libadsp-default-listener1",
        "libcdsprpc1",
        "libcdsp-default-listener1",
        "fastrpc",
    }.issubset(packages)
    assert packages["fastrpc"].name == "fastrpc_1.0.7-1flange1_arm64.deb"
    assert packages["libcdsprpc1"].name == (
        "libcdsprpc1_1.0.7-1flange1_arm64.deb"
    )
    assert packages["radxa-firmware-sc8280xp"].name == (
        "radxa-firmware-sc8280xp_0.2.41-1flange1_arm64.deb"
    )

    members = _read_ar_members(packages["fastrpc"])
    control = _read_tar_member(
        members["control.tar.gz"], "./control"
    ).decode("utf-8")
    assert "Package: fastrpc" in control
    assert "libadsp-default-listener1 (>= 1.0.7)" in control
    assert "libcdsprpc1 (>= 1.0.7)" in control
    assert "radxa-firmware-sc8280xp (= 0.2.41-1flange1)" in control
    control_tar = members["control.tar.gz"]
    control_names = _read_tar_names(control_tar)
    for name in ("postinst", "prerm", "postrm"):
        assert f"./{name}" in control_names
    assert "./triggers" not in control_names
    scripts = "\n".join(
        _read_tar_member(control_tar, f"./{name}").decode("utf-8")
        for name in ("postinst", "prerm", "postrm")
    )
    assert "adsprpcd.service" in scripts
    assert "cdsprpcd.service" in scripts
    assert "deb-systemd-helper" not in scripts
    for excluded in ("sdsprpcd.service", "gdsp0rpcd.service",
                     "gdsp1rpcd.service", "cdsp1rpcd.service"):
        assert excluded not in scripts
    for name in ("postinst", "prerm", "postrm"):
        assert _get_tar_info(control_tar, f"./{name}").mode == 0o755
    data = members["data.tar.gz"]
    names = _read_tar_names(data)
    assert "./usr/sbin/cdsprpcd" in names
    assert "./lib/systemd/system/fastrpc.service" in names
    assert "./usr/libexec/fastrpc/setup-dsp.sh" in names
    assert "./usr/lib/aarch64-linux-gnu/libcdsprpc.so.1.0.0" not in names
    assert (
        "./usr/share/qcom/sc8280xp/radxa/dragon-q8b/dsp/"
        "cdsp/fastrpc_shell_3"
    ) not in names

    library_payloads = {
        "libadsprpc1": "libadsprpc.so.1.0.0",
        "libadsp-default-listener1": "libadsp_default_listener.so.1.0.0",
        "libcdsprpc1": "libcdsprpc.so.1.0.0",
        "libcdsp-default-listener1": "libcdsp_default_listener.so.1.0.0",
    }
    for package, library in library_payloads.items():
        library_members = _read_ar_members(packages[package])
        library_names = _read_tar_names(library_members["data.tar.gz"])
        assert f"./usr/lib/aarch64-linux-gnu/{library}" in library_names
        triggers = _read_tar_member(
            library_members["control.tar.gz"], "./triggers"
        ).decode("utf-8")
        assert triggers.endswith("activate-noawait ldconfig\n")

    dsp_members = _read_ar_members(packages["radxa-firmware-sc8280xp"])
    dsp_data = dsp_members["data.tar.gz"]
    dsp_names = _read_tar_names(dsp_data)
    assert (
        "./usr/share/qcom/sc8280xp/radxa/dragon-q8b/dsp/"
        "cdsp/fastrpc_shell_3"
    ) in dsp_names
    dsp_link = _get_tar_info(dsp_data, "./usr/lib/dsp")
    assert dsp_link.issym()
    assert dsp_link.linkname == (
        "/usr/share/qcom/sc8280xp/radxa/dragon-q8b/dsp")


def test_q8b_fastrpc_test_uses_official_package_name(tmp_path: Path):
    """debug 验证工具应生成官方 `fastrpc-test` 包名。"""
    config = resolve_config("radxa-dragon-q8b", "default", "debug")
    builder = AppBuilder(
        docker=MagicMock(),
        source=SourceManager(
            sources_dir=tmp_path / "sources",
            project_root=_PROJECT_ROOT,
        ),
        config=config,
        context=WorkspaceContext(_PROJECT_ROOT, tmp_path, tmp_path / "build",
                                 Target(config["board"], config["product"], config["variant"])),
    )

    deb_path = builder.build_one("fastrpc-test").root().runtime_debs[0]

    assert deb_path.name == "fastrpc-test_1.0.7-1flange1_arm64.deb"
    members = _read_ar_members(deb_path)
    control = _read_tar_member(
        members["control.tar.gz"], "./control"
    ).decode("utf-8")
    assert "Package: fastrpc-test" in control
    assert "libcdsprpc1 (>= 1.0.7)" in control
    names = _read_tar_names(members["data.tar.gz"])
    assert "./usr/bin/fastrpc_test" in names
    assert "./usr/share/fastrpc_test/v68/libcalculator_skel.so" in names
    assert not any("/v75/" in name for name in names)


@pytest.fixture(scope="module", params=["aarch64", "armhf"])
def service_packages(request, tmp_path_factory):
    """构建 adbd，并检查 usbmoded 由真实依赖闭包一同交付。"""
    arch = request.param
    workspace = tmp_path_factory.mktemp(f"service-packages-{arch}")
    config = {
        "board": "test", "product": "default", "variant": "release",
        "architecture": {"userspace": arch, "kernel": "arm64", "bootloader": "arm64"},
        "rootfs": {"custom_packages": ["adbd"]},
    }
    def compile_fixture(command, *, cwd, env):
        # 此测试验证安装闭包与包契约；Rust 编译及行为由容器内 cargo test 验证。
        # 提供同架构的真实静态 ELF，继续经过完整包头与 ABI 校验。
        output = Path(cwd) / "out"
        output.mkdir()
        suffix = {"aarch64": "arm64", "armhf": "armhf"}[arch]
        for name in ("usbmoded", "usb-mode"):
            shutil.copy2(_PROJECT_ROOT / f"components/app/adbd/bin/adbd-{suffix}", output / name)

    docker = MagicMock()
    docker.run.side_effect = compile_fixture
    builder = AppBuilder(
        docker=docker,
        source=SourceManager(project_root=_PROJECT_ROOT, sources_dir=workspace / "sources"),
        config=config,
        context=WorkspaceContext(_PROJECT_ROOT, workspace, workspace / "build",
                                 Target("test", "default", "release")),
    )
    report = builder.build_one("adbd")
    assert report.validate()
    assert [item.name for item in report.ordered] == ["usbmoded", "adbd"]
    return arch, {item.name: _read_ar_members(item.runtime_debs[0]) for item in report.ordered}


def test_adbd_package_installs_matching_binary_and_unit(service_packages):
    arch, packages = service_packages
    data = packages["adbd"]["data.tar.gz"]
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        modes = {member.name: member.mode for member in archive.getmembers() if member.isfile()}
    assert modes == {
        "./usr/bin/adbd": 0o755,
        "./lib/systemd/system/usbmoded-adbd.service": 0o644,
    }
    suffix = {"aarch64": "arm64", "armhf": "armhf"}[arch]
    binary = _PROJECT_ROOT / f"components/app/adbd/bin/adbd-{suffix}"
    assert _read_tar_member(data, "./usr/bin/adbd") == binary.read_bytes()
    control = _read_tar_member(packages["adbd"]["control.tar.gz"], "./control").decode()
    assert "Package: adbd" in control.splitlines()
    assert f"Architecture: {suffix}" in control.splitlines()
    assert "Depends: usbmoded, libc6" in control.splitlines()


def test_usbmoded_package_installs_runtime_and_preserves_configuration(service_packages):
    _, packages = service_packages
    data = packages["usbmoded"]["data.tar.gz"]
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        modes = {member.name: member.mode for member in archive.getmembers() if member.isfile()}
    expected = {
        "./usr/sbin/usbmoded": 0o755,
        "./usr/sbin/usb-mode": 0o755,
        "./etc/usbmode/gadget.d/10-default.yaml": 0o644,
        "./etc/usbmode/scenes.d/10-common.yaml": 0o644,
        "./etc/udev/rules.d/61-usbmode.rules": 0o644,
        "./lib/systemd/system/usbmoded.service": 0o644,
        "./lib/systemd/system/usbmoded-mtp-server.service": 0o644,
    }
    assert expected.items() <= modes.items()
    assert not any("/python" in path or path.endswith(".py") for path in modes)
    assert not {"./usr/bin/usbmoded", "./usr/bin/usb-mode",
                "./lib/udev/rules.d/61-usbmode.rules"} & modes.keys()
    control_tar = packages["usbmoded"]["control.tar.gz"]
    control = _read_tar_member(control_tar, "./control").decode()
    assert "Depends: udev" in control.splitlines()
    assert set(_read_tar_member(control_tar, "./conffiles").decode().splitlines()) == {
        "/etc/usbmode/gadget.d/10-default.yaml",
        "/etc/usbmode/scenes.d/10-common.yaml",
    }


def test_service_packages_enable_only_usbmoded(service_packages):
    """adbd 等待 FunctionFS 就绪，由 usbmoded 管理启动时机。"""
    _, packages = service_packages
    adbd_control = packages["adbd"]["control.tar.gz"]
    adbd_postinst = _read_tar_member(adbd_control, "./postinst").decode()
    assert "systemctl enable" not in adbd_postinst
    assert ".wants" not in adbd_postinst
    assert "./conffiles" not in _read_tar_names(adbd_control)
    usb_control = packages["usbmoded"]["control.tar.gz"]
    usb_postinst = _read_tar_member(usb_control, "./postinst").decode()
    assert "systemctl enable usbmoded.service" in usb_postinst
    assert (
        "ln -sf /lib/systemd/system/usbmoded.service /etc/systemd/system/$target.wants/"
        in usb_postinst
    )
    assert "systemctl enable usbmoded-mtp-server.service" not in usb_postinst



class TestEngineAppIntegration:
    """真实空 App 报告也经过引擎成功清单，不能用旧 dict 伪造成功。"""

    def test_app报告与引擎manifest联通(self, tmp_path):
        from builder.workspace import WorkspaceContext, Target
        from builder.artifacts import ArtifactManifest
        context = WorkspaceContext(tmp_path, tmp_path, tmp_path / '.build',
                                   Target('board', 'default', 'release'))
        config = {'board': 'board', 'product': 'default', 'variant': 'release', 'platform': 'rockchip',
                  'architecture': {'userspace': 'aarch64', 'kernel': 'arm64', 'bootloader': 'arm64'},
                  'rootfs': {'custom_packages': []}}
        engine = BuildEngine(config, context=context, output=MagicMock())
        engine.build('app')
        report_path = context.target_dir / 'apps/build-report.json'
        assert report_path.is_file()
        manifest = ArtifactManifest.load(context.target_dir / 'app/manifest.json')
        assert manifest and manifest.validate()
        assert manifest.artifacts[0].path == report_path
        assert engine._app_report.runtime_debs == ()
        identity = manifest.identity
        engine.build('app')
        assert ArtifactManifest.load(context.target_dir / 'app/manifest.json').identity == identity
