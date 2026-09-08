"""UNO Q 的固定输入、Android 容器与 EFI 边界回归。"""

import gzip
import struct
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from builder.config.jsonnet import JsonnetConfigLoader
from builder.config.validate import validate_canonical_config
from builder.paths import PROJECT_ROOT
from builder.platforms.qualcommqrb2210 import required_artifacts
from builder.platforms.qualcommqrb2210.boot import (
    Qrb2210BootBuilder, render_entry, validate_arm64_efi,
)
from builder.platforms.qualcommqrb2210.bootloader import (
    extract_firmware, pack_android_v0, pack_uboot_payload,
)
from builder.platforms.qualcommqrb2210.kernel import Qrb2210KernelBuilder


@pytest.mark.parametrize("variant", ["debug", "release"])
def test_unoq_pins_sources_and_physical_partitions(variant):
    config = JsonnetConfigLoader(PROJECT_ROOT).evaluate_board(
        "arduino-uno-q", "default", variant)
    validate_canonical_config(config)
    assert config["sources"]["linux-unoq"]["commit"] == (
        "122c2c22d838ca826e7f4e7360df96fb4e8f7ad2")
    assert config["sources"]["u-boot-unoq"]["commit"] == (
        "8008ca96a4dc53ddb3e51b96ea7e86d881ab7969")
    assert config["kernel"]["device_tree"]["name"] == "qrb2210-arduino-imola"
    assert config["bootloader"]["device_tree"] == "qcom/qrb2210-arduino-imola"
    assert [p["name"] for p in config["partitions"]["entries"]] == [
        "efi", "rootfs", "userdata"]
    assert not config["recovery"]["enabled"]
    assert config["kernel"]["config"]["CONFIG_DEBUG_INFO_NONE"] == (
        "y" if variant == "release" else "n")
    assert config["kernel"]["config"]["CONFIG_DEBUG_INFO_DWARF_TOOLCHAIN_DEFAULT"] == (
        "y" if variant == "debug" else "n")
    user = config["rootfs"]["users"]["arduino"]
    if variant == "release":
        assert "password" not in user
    else:
        assert user["password"] == "arduino"


def test_recovery_archive_rejects_path_escape(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../escape", b"payload")
    with pytest.raises(ValueError, match="不安全路径"):
        extract_firmware(archive, tmp_path / "unpacked", "loader.elf")
    assert not (tmp_path / "escape").exists()


def test_recovery_archive_requires_loader_and_xml(tmp_path):
    archive = tmp_path / "good.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("firmware/loader.elf", b"loader")
        output.writestr("firmware/rawprogram0.xml", b"<data/>")
        output.writestr("firmware/patch0.xml", b"<patches/>")
    root = extract_firmware(archive, tmp_path / "out", "loader.elf")
    assert root == tmp_path / "out/firmware"
    with pytest.raises(ValueError, match="唯一"):
        extract_firmware(archive, tmp_path / "missing", "other.elf")


def test_uboot_payload_is_deterministic_gzip_with_dtb(tmp_path):
    binary, dtb = tmp_path / "u-boot.bin", tmp_path / "board.dtb"
    binary.write_bytes(b"uboot-binary" * 100)
    dtb.write_bytes(b"\xd0\x0d\xfe\xed" + b"dtb")
    first, second = tmp_path / "first", tmp_path / "second"
    pack_uboot_payload(binary, dtb, first)
    pack_uboot_payload(binary, dtb, second)
    assert first.read_bytes() == second.read_bytes()
    payload = first.read_bytes()
    assert payload.endswith(dtb.read_bytes())
    assert gzip.decompress(payload[:-len(dtb.read_bytes())]) == binary.read_bytes()


def test_android_v0_load_addresses_and_page_boundaries(tmp_path):
    payload, image = tmp_path / "payload", tmp_path / "boot.img"
    payload.write_bytes(b"K" * 4097)
    pack_android_v0(payload, image)
    data = image.read_bytes()
    assert data[:8] == b"ANDROID!"
    assert struct.unpack_from("<10I", data, 8) == (
        4097, 0x80008000, 0, 0, 0, 0, 0x80000100, 4096, 0, 0)
    assert data[4096:8193] == payload.read_bytes()
    assert len(data) == 12288
    assert set(data[8193:]) == {0}
    payload.write_bytes(b"K" * (4 * 1024 * 1024))
    with pytest.raises(ValueError, match="4 MiB"):
        pack_android_v0(payload, image)


@pytest.mark.parametrize("machine,accepted", [(0xAA64, True), (0x8664, False)])
def test_efi_requires_arm64_machine(tmp_path, machine, accepted):
    data = bytearray(128)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3c, 64)
    data[64:68] = b"PE\0\0"
    struct.pack_into("<H", data, 68, machine)
    path = tmp_path / "boot.efi"
    path.write_bytes(data)
    if accepted:
        validate_arm64_efi(path)
    else:
        with pytest.raises(ValueError, match="ARM64"):
            validate_arm64_efi(path)


def test_efi_entry_uses_kernel_dtb_and_initrd():
    text = render_entry({"boot": {"kernel_args": "root=PARTLABEL=rootfs rootwait"}}, "unoq")
    assert "linux /Image\n" in text
    assert "initrd /initrd.img\n" in text
    assert "devicetree /dtb/unoq.dtb\n" in text
    with pytest.raises(ValueError, match="单行"):
        render_entry({"boot": {"kernel_args": "root=/dev/foo\nlinux /bad"}}, "unoq")


def test_kernel_builds_combined_dtb_and_modules(tmp_path):
    builder = Qrb2210KernelBuilder(Mock(), Mock())
    builder.make = Mock()
    config = {"kernel": {"device_tree": {"directory": "qcom", "name": "qrb2210-arduino-imola"}}}
    builder.compile(tmp_path, config)
    assert builder.make.call_args_list[0].args[1] == [
        "Image", "qcom/qrb2210-arduino-imola.dtb", "modules"]
    assert builder.make.call_args_list[1].args[1] == ["modules_install"]


def test_boot_artifacts_are_required(tmp_path):
    config = {"bootloader": {"firehose_loader": "prog_firehose_ddr.elf"}}
    outputs = required_artifacts("bootloader", tmp_path, config)
    assert {p.name for p in outputs} == {"firmware", "firehose", "uboot"}
    assert all(p.required and not p.allow_empty for p in outputs)
    assert {p.path.name for p in required_artifacts("rootfs", tmp_path, config)} == {
        "rootfs.img", "userdata.img", "initrd.img", "bootaa64.efi", "packages.manifest"}


def test_boot_refuses_missing_declared_initrd_before_packaging(tmp_path):
    kernel = tmp_path / "kernel"
    kernel.mkdir()
    (kernel / "Image").write_bytes(b"kernel")
    (kernel / "unoq.dtb").write_bytes(b"dtb")
    docker = Mock()
    builder = Qrb2210BootBuilder(docker, Mock())
    builder.context = SimpleNamespace(target_dir=tmp_path)
    config = {"kernel": {"device_tree": {"directory": "qcom", "name": "unoq"}}}
    with pytest.raises(FileNotFoundError, match="initrd"):
        builder.build(config)
    docker.run.assert_not_called()
