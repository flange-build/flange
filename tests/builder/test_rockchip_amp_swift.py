"""Rockchip RT-Thread AMP Embedded Swift 构建接线测试。"""

import subprocess
from pathlib import Path

import pytest

from builder.app_spec import SwiftBuildConfig
from builder.docker import BuildError
from builder.platforms.rockchip.amp import RockchipAmpBuilder


class FakeDocker:
    """记录命令，并在 swift build 时伪造 SwiftPM static archive。"""

    def __init__(self, nm_stdout: str = ""):
        self.calls = []
        self.nm_stdout = nm_stdout

    def run(self, cmd, **kwargs):
        self.calls.append((list(cmd), kwargs))
        if cmd[:2] == ["swift", "build"]:
            scratch = Path(cmd[cmd.index("--scratch-path") + 1])
            product = cmd[cmd.index("--product") + 1]
            out = scratch / "armv7-none-none-eabi" / "release"
            out.mkdir(parents=True, exist_ok=True)
            (out / f"lib{product}.a").write_bytes(b"!<arch>\n")
        if cmd[:2] == ["arm-none-eabi-nm", "-u"]:
            return subprocess.CompletedProcess(
                cmd, 0, stdout=self.nm_stdout, stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


def _builder(fake: FakeDocker) -> RockchipAmpBuilder:
    return RockchipAmpBuilder(fake, source=None)


def _swift_cfg(**overrides) -> SwiftBuildConfig:
    values = {
        "enabled": True,
        "package_path": ".",
        "product": "AmpLogic",
        "c_header": "include/swift_bridge.h",
        "target_triple": "armv7-none-none-eabi",
        "extra_flags": [],
        "allowed_undefined": [],
    }
    values.update(overrides)
    return SwiftBuildConfig(**values)


def _make_app(tmp_path: Path) -> Path:
    app_dir = tmp_path / "app"
    (app_dir / "applications").mkdir(parents=True)
    (app_dir / "include").mkdir()
    (app_dir / "Package.swift").write_text("// swift package\n")
    (app_dir / "include" / "swift_bridge.h").write_text("#pragma once\n")
    return app_dir


def test_prepare_rtthread_swift_builds_archive_and_sconscript(tmp_path):
    """SwiftPM archive 应复制到 staged BSP，并由 generated SConscript 链接。"""
    fake = FakeDocker(nm_stdout="         U memcpy\n")
    builder = _builder(fake)
    app_dir = _make_app(tmp_path)
    bsp_tmp = tmp_path / "bsp"
    (bsp_tmp / "applications").mkdir(parents=True)

    archive = builder._prepare_rtthread_swift(
        app_dir, bsp_tmp, _swift_cfg(extra_flags=["-Xswiftc", "-Osize"]))

    assert archive == bsp_tmp / "applications" / "flange_swift" / "libAmpLogic.a"
    assert archive.exists()
    assert (bsp_tmp / "applications" / "include" / "swift_bridge.h").exists()

    swift_build = next(cmd for cmd, _ in fake.calls if cmd[:2] == ["swift", "build"])
    assert "--package-path" in swift_build
    assert str(app_dir) in swift_build
    assert "--scratch-path" in swift_build
    assert "--product" in swift_build
    assert "AmpLogic" in swift_build
    assert "--triple" in swift_build
    assert "armv7-none-none-eabi" in swift_build
    assert "-enable-experimental-feature" in swift_build
    assert "Embedded" in swift_build
    assert "-Osize" in swift_build
    assert "-no-allocations" in swift_build
    assert "-disable-stack-protector" in swift_build

    sconscript = (bsp_tmp / "applications" / "SConscript").read_text()
    assert "LIBS = ['AmpLogic']" in sconscript
    assert "flange_swift" in sconscript
    assert "include" in sconscript


def test_prepare_rtthread_swift_rejects_custom_sconscript(tmp_path):
    """启用 Swift 时 app 自带 applications/SConscript 会被明确拒绝。"""
    builder = _builder(FakeDocker())
    app_dir = _make_app(tmp_path)
    (app_dir / "applications" / "SConscript").write_text("# custom\n")
    bsp_tmp = tmp_path / "bsp"
    (bsp_tmp / "applications").mkdir(parents=True)

    with pytest.raises(ValueError, match="applications/SConscript"):
        builder._prepare_rtthread_swift(app_dir, bsp_tmp, _swift_cfg())


def test_swift_archive_unexpected_undefined_symbol_rejected(tmp_path):
    """未列入白名单的 Swift runtime 符号应在最终链接前失败。"""
    fake = FakeDocker(nm_stdout="         U swift_allocObject\n")
    builder = _builder(fake)
    app_dir = _make_app(tmp_path)
    bsp_tmp = tmp_path / "bsp"
    (bsp_tmp / "applications").mkdir(parents=True)

    with pytest.raises(BuildError, match="未列入白名单"):
        builder._prepare_rtthread_swift(app_dir, bsp_tmp, _swift_cfg())


def test_parse_nm_undefined_output_skips_archive_member_headers():
    output = """
foo.o:
         U memcpy
         U swift_handle_message
"""
    assert RockchipAmpBuilder._parse_nm_undefined_output(output) == [
        "memcpy",
        "swift_handle_message",
    ]
