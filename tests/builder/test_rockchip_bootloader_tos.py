"""RK3506 TOS-only U-Boot、显式 INI 与 AMP Kconfig 测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from builder.platforms.rockchip.bootloader import RockchipBootloaderBuilder


LOADER_INI = """\
[LOADER_OPTION]
FlashData=bin/rk35/rk3506b_ddr.bin
FlashBoot=bin/rk35/rk3506_spl.bin
[OUTPUT]
PATH=rk3506_spl_loader.bin
IDB_PATH=rk3506_idblock.img
[SYSTEM]
NEWIDB=true
"""

TOS_INI = """\
[TOS]
TOSTA=bin/rk35/rk3506_tee.bin
ADDR=0x1000
"""


class FakeSource:
    def __init__(self, firmware_dir: Path):
        self.firmware_dir = firmware_dir

    def ensure_firmware(self, config: dict) -> Path:
        assert config["platform"] == "rockchip"
        return self.firmware_dir


class FakeDocker:
    def __init__(self):
        self.commands: list[list[str]] = []

    def run(self, cmd: list[str], **kwargs):
        self.commands.append(list(cmd))
        if cmd[0].endswith("make_fit_optee.sh"):
            return SimpleNamespace(
                stdout="/dts-v1/;\n/ { images { optee {}; }; };\n")
        return SimpleNamespace(stdout="")


class RecordingBuilder(RockchipBootloaderBuilder):
    def __init__(self, docker, source):
        super().__init__(docker, source)
        self.make_calls: list[tuple[list[str], dict]] = []

    def make(self, src_dir: Path, targets: list, **kwargs):
        self.make_calls.append((list(targets), dict(kwargs)))


class FragmentBuilder(RecordingBuilder):
    """模拟 U-Boot fragment target 对 .config 的顺序合并。"""

    def make(self, src_dir: Path, targets: list, **kwargs):
        super().make(src_dir, targets, **kwargs)
        target = targets[0]
        config_path = src_dir / ".config"
        if target == "rk3506_defconfig":
            config_path.write_text("CONFIG_ARM=y\n")
        elif target == "rk3506b.config":
            with config_path.open("a") as stream:
                stream.write('CONFIG_LOADER_INI="RK3506BMINIALL.ini"\n')
        elif target == "rk3506-amp.config":
            with config_path.open("a") as stream:
                stream.write("CONFIG_AMP=y\nCONFIG_ROCKCHIP_AMP=y\n")


def _firmware_tree(tmp_path: Path) -> Path:
    firmware = tmp_path / "rkbin"
    (firmware / "RKBOOT").mkdir(parents=True)
    (firmware / "RKTRUST").mkdir()
    (firmware / "bin/rk35").mkdir(parents=True)
    (firmware / "tools").mkdir()
    (firmware / "RKBOOT/RK3506BMINIALL.ini").write_text(LOADER_INI)
    (firmware / "RKTRUST/RK3506TOS.ini").write_text(TOS_INI)
    (firmware / "bin/rk35/rk3506_tee.bin").write_bytes(b"TEE")
    (firmware / "tools/boot_merger").write_bytes(b"tool")
    (firmware / "rk3506_spl_loader.bin").write_bytes(b"loader")
    (firmware / "rk3506_idblock.img").write_bytes(b"idblock")
    return firmware


def _source_tree(tmp_path: Path) -> Path:
    source = tmp_path / "u-boot"
    generator = source / "arch/arm/mach-rockchip/make_fit_optee.sh"
    generator.parent.mkdir(parents=True)
    generator.write_text("#!/bin/bash\n")
    (source / "tools").mkdir()
    return source


def _config() -> dict:
    return {
        "platform": "rockchip",
        "architecture": {
            "userspace": "armhf", "kernel": "arm", "bootloader": "arm",
        },
        "rkbin": {
            "ini_prefix": "RK3506B",
            "loader_ini": "RK3506BMINIALL.ini",
            "trust_ini": "RK3506TOS.ini",
            "mkimage_chip": "rk3506",
        },
        "bootloader": {
            "cross_compile": "arm-linux-gnueabi-",
            "trust_mode": "tos",
            "idbloader_method": "boot_merger",
            "idbloader_selfbuilt_spl": False,
            "defconfig": [
                "rk3506_defconfig",
                "rk3506b.config",
                "rk3506-amp.config",
            ],
        },
        "amp": {"enabled": True},
        "jobs": 2,
    }


def test_parse_tos_ini_returns_tee_and_address(tmp_path):
    firmware = _firmware_tree(tmp_path)
    builder = RockchipBootloaderBuilder(docker=None, source=None)

    tee, address = builder._parse_tos_ini(
        firmware / "RKTRUST/RK3506TOS.ini", firmware)

    assert tee == firmware / "bin/rk35/rk3506_tee.bin"
    assert address == "0x1000"


def test_tos_compile_uses_tee_without_bl31_and_collects_dynamic_outputs(
    tmp_path,
):
    firmware = _firmware_tree(tmp_path)
    source = _source_tree(tmp_path)
    docker = FakeDocker()
    builder = RecordingBuilder(docker, FakeSource(firmware))

    builder.compile(source, _config())

    assert not (source / "bl31.elf").exists()
    assert (source / "tee.bin").read_bytes() == b"TEE"
    generator_call = next(
        cmd for cmd in docker.commands if cmd[0].endswith("make_fit_optee.sh"))
    assert generator_call[-2:] == ["-t", "0x1000"]
    fit_targets, fit_kwargs = next(
        call for call in builder.make_calls if call[0] == ["u-boot.itb"])
    assert fit_targets == ["u-boot.itb"]
    assert fit_kwargs["arch"] == "arm"
    assert fit_kwargs["cross"] == "arm-linux-gnueabi-"
    assert any(item.startswith("TEE=") for item in fit_kwargs["extra"])
    assert not any(item.startswith("BL31=") for item in fit_kwargs["extra"])
    assert any(item.startswith("U_BOOT_ITS=") for item in fit_kwargs["extra"])
    assert (source / "idbloader.img").read_bytes() == b"idblock"

    outputs = builder.collect(source, _config())
    assert outputs["miniloader"] == firmware / "rk3506_spl_loader.bin"
    assert outputs["idbloader"] == source / "idbloader.img"
    assert outputs["bootloader"] == source / "u-boot.itb"


def test_explicit_ini_names_override_prefix_compatibility(tmp_path):
    firmware = _firmware_tree(tmp_path)
    builder = RockchipBootloaderBuilder(docker=None, source=None)

    assert builder._loader_ini_path(firmware, _config()).name == (
        "RK3506BMINIALL.ini")
    assert builder._trust_ini_path(firmware, _config()).name == "RK3506TOS.ini"


def test_amp_fragments_keep_both_required_options(tmp_path):
    builder = FragmentBuilder(docker=None, source=None)

    builder.configure(tmp_path, _config())

    assert [call[0] for call in builder.make_calls] == [
        ["rk3506_defconfig"],
        ["rk3506b.config"],
        ["rk3506-amp.config"],
    ]
    text = (tmp_path / ".config").read_text()
    assert "CONFIG_AMP=y" in text
    assert "CONFIG_ROCKCHIP_AMP=y" in text


def test_amp_config_rejects_missing_rockchip_amp_option(tmp_path):
    (tmp_path / ".config").write_text("CONFIG_AMP=y\n")

    with pytest.raises(ValueError, match="CONFIG_ROCKCHIP_AMP"):
        RockchipBootloaderBuilder._validate_amp_options(tmp_path, _config())


def test_bl31_bl32_parser_regression(tmp_path):
    firmware = tmp_path / "rkbin"
    (firmware / "bin").mkdir(parents=True)
    (firmware / "bin/bl31.elf").write_bytes(b"BL31")
    (firmware / "bin/tee.bin").write_bytes(b"BL32")
    ini = tmp_path / "RK3568TRUST.ini"
    ini.write_text(
        "[BL31_OPTION]\nPATH=bin/bl31.elf\n"
        "[BL32_OPTION]\nPATH=bin/tee.bin\n")
    builder = RockchipBootloaderBuilder(docker=None, source=None)

    bl31, bl32 = builder._parse_trust_ini(ini, firmware)

    assert bl31 == firmware / "bin/bl31.elf"
    assert bl32 == firmware / "bin/tee.bin"
