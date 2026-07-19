"""Rockchip RT-Thread AMP Embedded Swift 构建接线测试。"""

import subprocess
from pathlib import Path

import pytest

from builder.app_spec import SwiftBuildConfig
from builder.docker import BuildError
from builder.platforms.rockchip.amp import RockchipAmpBuilder


class FakeDocker:
    """记录命令，并在 swift build 时伪造 SwiftPM static archive。"""

    def __init__(
        self,
        readelf_output: str = (
            "Tag_ABI_VFP_args: VFP registers\n"
            "Tag_ABI_enum_size: small\n"
        ),
        *,
        nm_output: str = "",
        section_output: str = "",
    ):
        self.calls = []
        self.readelf_output = readelf_output
        self.nm_output = nm_output
        self.section_output = section_output

    def run(self, cmd, **kwargs):
        self.calls.append((list(cmd), kwargs))
        if cmd[:2] == ["swift", "build"]:
            scratch = Path(cmd[cmd.index("--scratch-path") + 1])
            product = cmd[cmd.index("--product") + 1]
            out = scratch / "armv7-none-none-eabi" / "release"
            out.mkdir(parents=True, exist_ok=True)
            (out / f"lib{product}.a").write_bytes(b"!<arch>\n")
        if str(cmd[0]).endswith("arm-none-eabi-nm"):
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=self.nm_output,
                stderr="",
            )
        if str(cmd[0]).endswith("arm-none-eabi-readelf"):
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=(
                    self.section_output
                    if "-SW" in cmd
                    else self.readelf_output
                ),
                stderr="",
            )
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
    fake = FakeDocker()
    builder = _builder(fake)
    app_dir = _make_app(tmp_path)
    bsp_tmp = tmp_path / "bsp"
    (bsp_tmp / "applications").mkdir(parents=True)

    archive = builder._prepare_rtthread_swift(
        app_dir,
        bsp_tmp,
        _swift_cfg(extra_flags=["-Xswiftc", "-Osize"]),
        "cortex-a7",
        [
            "-mcpu=cortex-a7",
            "-mfloat-abi=hard",
            "-mfpu=neon-vfpv4",
            "-marm",
        ],
    )

    assert archive == bsp_tmp / "applications" / "flange_swift" / "libAmpLogic.a"
    assert archive.exists()
    assert (bsp_tmp / "applications" / "include" / "swift_bridge.h").exists()

    swift_build, swift_build_kwargs = next(
        (cmd, kwargs)
        for cmd, kwargs in fake.calls
        if cmd[:2] == ["swift", "build"]
    )
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
    target_cpu_index = swift_build.index("-target-cpu")
    assert swift_build[target_cpu_index + 1] == "-Xswiftc"
    assert swift_build[target_cpu_index + 2] == "cortex-a7"
    assert "-mcpu=cortex-a7" in swift_build
    assert "-mfpu=neon-vfpv4" in swift_build
    assert "-fshort-enums" in swift_build
    assert "-fno-short-enums" not in swift_build
    assert "-mcpu=cortex-a55+crypto" not in swift_build
    assert swift_build_kwargs["env"] == {
        "FLUXION_EMBEDDED_PACKAGE_ONLY": "1"
    }

    readelf_cmd, readelf_kwargs = next(
        (cmd, kwargs)
        for cmd, kwargs in fake.calls
        if str(cmd[0]).endswith("arm-none-eabi-readelf")
    )
    assert readelf_cmd[1:] == ["-A", str(archive)]
    assert readelf_kwargs["env"] == {"LC_ALL": "C"}

    sconscript = (bsp_tmp / "applications" / "SConscript").read_text()
    assert "LIBS = ['AmpLogic']" in sconscript
    assert "flange_swift" in sconscript
    assert "include" in sconscript


def test_hard_float_abi_gate_accepts_vfp_registers(tmp_path):
    artifact = tmp_path / "libAmpLogic.a"
    artifact.write_bytes(b"!<arch>\n")
    builder = _builder(FakeDocker())

    builder._assert_hard_float_abi(artifact)


def test_hard_float_abi_gate_rejects_missing_vfp_registers(tmp_path):
    artifact = tmp_path / "libAmpLogic.a"
    artifact.write_bytes(b"!<arch>\n")
    builder = _builder(FakeDocker("Tag_CPU_arch: v7\n"))

    with pytest.raises(BuildError, match="Tag_ABI_VFP_args"):
        builder._assert_hard_float_abi(artifact)


def test_hard_float_abi_gate_rejects_fixed_enum_abi(tmp_path):
    artifact = tmp_path / "libAmpLogic.a"
    artifact.write_bytes(b"!<arch>\n")
    builder = _builder(FakeDocker(
        "Tag_ABI_VFP_args: VFP registers\n"
        "Tag_ABI_enum_size: int\n"
    ))

    with pytest.raises(BuildError, match="enum ABI"):
        builder._assert_hard_float_abi(artifact)


def _heap_fake(begin: int, end: int) -> FakeDocker:
    size = end - begin
    return FakeDocker(
        nm_output=(
            f"{begin:08x} B __heap_begin\n"
            f"{end:08x} B __heap_end\n"
        ),
        section_output=(
            "There are 12 section headers:\n"
            f"  [ 9] .heap NOBITS {begin:08x} 047000 {size:06x} "
            "00  WA  0   0 16\n"
        ),
    )


def _heap_runtime(minimum: int = 0x80000) -> dict:
    return {"minimum_heap_size": minimum}


def _heap_memory() -> dict:
    return {"cpu_base": 0x03E00000, "dram_size": 0x00100000}


def test_rtthread_heap_gate_accepts_required_capacity(tmp_path):
    artifact = tmp_path / "rtthread.elf"
    artifact.write_bytes(b"ELF")
    builder = _builder(_heap_fake(0x03E70000, 0x03F00000))

    available = builder._assert_rtthread_heap_capacity(
        artifact,
        _heap_runtime(),
        _heap_memory(),
    )

    assert available == 0x90000


def test_rtthread_heap_gate_rejects_too_small_capacity(tmp_path):
    artifact = tmp_path / "rtthread.elf"
    artifact.write_bytes(b"ELF")
    builder = _builder(_heap_fake(0x03E90000, 0x03F00000))

    with pytest.raises(BuildError, match="小于.*minimum_heap_size"):
        builder._assert_rtthread_heap_capacity(
            artifact,
            _heap_runtime(),
            _heap_memory(),
        )


def test_rtthread_heap_gate_rejects_missing_symbol(tmp_path):
    artifact = tmp_path / "rtthread.elf"
    artifact.write_bytes(b"ELF")
    fake = _heap_fake(0x03E70000, 0x03F00000)
    fake.nm_output = "03e70000 B __heap_begin\n"
    builder = _builder(fake)

    with pytest.raises(BuildError, match="__heap_end"):
        builder._assert_rtthread_heap_capacity(
            artifact,
            _heap_runtime(),
            _heap_memory(),
        )


def test_prepare_rtthread_swift_does_not_run_archive_undefined_policy(tmp_path):
    """Swift archive 未定义符号不再由 builder 预检查，交给最终链接器处理。"""
    fake = FakeDocker()
    builder = _builder(fake)
    app_dir = _make_app(tmp_path)
    bsp_tmp = tmp_path / "bsp"
    (bsp_tmp / "applications").mkdir(parents=True)

    builder._prepare_rtthread_swift(
        app_dir,
        bsp_tmp,
        _swift_cfg(),
        "cortex-a7",
        ["-mcpu=cortex-a7", "-mfloat-abi=hard", "-marm"],
    )

    assert not any(
        cmd[:2] == ["arm-none-eabi-nm", "-u"]
        for cmd, _ in fake.calls
    )


def test_prepare_rtthread_swift_rejects_custom_sconscript(tmp_path):
    """启用 Swift 时 app 自带 applications/SConscript 会被明确拒绝。"""
    builder = _builder(FakeDocker())
    app_dir = _make_app(tmp_path)
    (app_dir / "applications" / "SConscript").write_text("# custom\n")
    bsp_tmp = tmp_path / "bsp"
    (bsp_tmp / "applications").mkdir(parents=True)

    with pytest.raises(ValueError, match="applications/SConscript"):
        builder._prepare_rtthread_swift(
            app_dir,
            bsp_tmp,
            _swift_cfg(),
            "cortex-a7",
            ["-mcpu=cortex-a7", "-mfloat-abi=hard", "-marm"],
        )


def test_rk3506_swift_arch_matches_rtthread_bsp():
    """RK3506 Swift/C 对象必须匹配 BSP 的 Cortex-A7 hard-float ABI。"""
    builder = _builder(FakeDocker())

    swift_cpu, c_flags = builder._rtthread_swift_arch_flags("rk3506")

    assert swift_cpu == "cortex-a7"
    assert "-mcpu=cortex-a7" in c_flags
    assert "-mfloat-abi=hard" in c_flags
    assert "-mfpu=neon-vfpv4" in c_flags
    assert "-marm" in c_flags
    assert not any("cortex-a55" in flag for flag in c_flags)


def test_rk3568_swift_arch_remains_cortex_a55():
    """既有 RK3568 构建继续使用它自己的 BSP 架构配置。"""
    builder = _builder(FakeDocker())

    swift_cpu, c_flags = builder._rtthread_swift_arch_flags("rk3568")

    assert swift_cpu == "cortex-a55"
    assert "-mcpu=cortex-a55+crypto" in c_flags
