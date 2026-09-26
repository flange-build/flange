"""Qualcomm UFS 多 LUN 启动固件刷写包：校验、暂存与 edl-ng 单会话编排。"""

import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from builder.flash import qualcomm_ufs
from builder.flash.execute import _cli_main
from builder.flash.generate import _ufs_firmware
from builder.flash.model import FlashConfig, FlashError, UfsFirmwareConfig
from builder.flash.strategy import QualcommFlashStrategy

SECTOR = 4096


def _program(label, lun, filename, start="6", sectors="1"):
    return (f'<program SECTOR_SIZE_IN_BYTES="{SECTOR}" filename="{filename}" label="{label}"'
            f' num_partition_sectors="{sectors}" physical_partition_number="{lun}"'
            f' start_sector="{start}"/>')


def _write_xml(path: Path, *nodes: str) -> None:
    path.write_text('<?xml version="1.0" ?>\n<data>\n' + "\n".join(nodes) + "\n</data>\n")


@pytest.fixture
def target(tmp_path):
    """RUBIK Pi 3 形态的最小产物目录：LUN1 xbl、LUN4 dtb_a/uefi_a、LUN0 raw.img。"""
    firmware = tmp_path / qualcomm_ufs.FIRMWARE_DIR
    firmware.mkdir(parents=True)
    for name in ("prog_firehose_ddr.elf", "xbl.elf", "uefi.elf",
                 "gpt_main1.bin", "gpt_main4.bin"):
        (firmware / name).write_bytes(b"\x7fELF" + name.encode())
    _write_xml(firmware / "rawprogram1.xml",
               _program("xbl_a", "1", "xbl.elf"),
               _program("PrimaryGPT", "1", "gpt_main1.bin", start="0"),
               _program("last_parti", "1", ""))
    _write_xml(firmware / "rawprogram4.xml",
               _program("dtb_a", "4", "dtb.bin"),
               _program("uefi_a", "4", "uefi.elf"),
               _program("PrimaryGPT", "4", "gpt_main4.bin", start="0"))
    for lun in ("1", "4"):
        _write_xml(firmware / f"patch{lun}.xml",
                   f'<patch physical_partition_number="{lun}" start_sector="2"/>')
    (tmp_path / "boot").mkdir()
    (tmp_path / "boot" / "dtb.bin").write_bytes(b"FAT")
    (tmp_path / "image").mkdir()
    (tmp_path / "image" / "raw.img").write_bytes(b"\0" * (3 * SECTOR))
    return tmp_path


def _config(**overrides) -> FlashConfig:
    config = FlashConfig(
        platform="qualcommqcs6490", flash_tool="edl-ng", board="thundercomm-rubikpi3",
        product="default", variant="release", soc="qcs6490", sector_size=SECTOR,
        ufs_firmware=UfsFirmwareConfig(
            loader="prog_firehose_ddr.elf",
            rawprogram=["rawprogram1.xml", "rawprogram4.xml"],
            patch=["patch1.xml", "patch4.xml"],
        ),
    )
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def test_暂存目录链接全部输入并生成lun0系统盘清单(target, tmp_path):
    stage = tmp_path / "stage"
    stage.mkdir()

    xmls = qualcomm_ufs.stage_bundle(target, _config(), stage)

    assert xmls == ["rawprogram0.xml", "rawprogram1.xml", "rawprogram4.xml",
                    "patch1.xml", "patch4.xml"]
    assert os.readlink(stage / qualcomm_ufs.SYSTEM_STAGED) == str(
        (target / "image/raw.img").resolve())
    # 固件与 dtb.bin 为独立副本：刷写工具的主机侧 GPT 补丁不能改写已发布产物。
    for name in ("dtb.bin", "xbl.elf", "uefi.elf", "gpt_main1.bin", "rawprogram4.xml",
                 "patch1.xml"):
        assert (stage / name).is_file() and not (stage / name).is_symlink(), name
    (stage / "gpt_main1.bin").write_bytes(b"patched")
    assert (target / qualcomm_ufs.FIRMWARE_DIR / "gpt_main1.bin").read_bytes() != b"patched"
    assert (stage / "dtb.bin").read_bytes() == b"FAT"
    program = ET.parse(stage / "rawprogram0.xml").getroot().find("program")
    assert program.get("filename") == qualcomm_ufs.SYSTEM_STAGED
    assert program.get("physical_partition_number") == "0"
    assert program.get("start_sector") == "0"
    assert program.get("num_partition_sectors") == "3"
    assert program.get("SECTOR_SIZE_IN_BYTES") == str(SECTOR)


def test_固件xml不得写lun0(target):
    firmware = target / qualcomm_ufs.FIRMWARE_DIR
    _write_xml(firmware / "rawprogram1.xml", _program("efi", "0", "xbl.elf"))

    with pytest.raises(FlashError, match="LUN0"):
        qualcomm_ufs.validate_bundle(target, _config())


def test_patch不得修改lun0(target):
    _write_xml(target / qualcomm_ufs.FIRMWARE_DIR / "patch1.xml",
               '<patch physical_partition_number="0" start_sector="2"/>')

    with pytest.raises(FlashError, match="LUN0"):
        qualcomm_ufs.validate_bundle(target, _config())


def test_拒绝git_lfs指针冒充固件(target):
    (target / qualcomm_ufs.FIRMWARE_DIR / "uefi.elf").write_bytes(
        b"version https://git-lfs.github.com/spec/v1\noid sha256:00\nsize 1\n")

    with pytest.raises(FlashError, match="LFS"):
        qualcomm_ufs.validate_bundle(target, _config())


def test_缺少boot产出的dtb分区镜像时拒绝(target):
    (target / "boot" / "dtb.bin").unlink()

    with pytest.raises(FlashError, match="dtb.bin"):
        qualcomm_ufs.validate_bundle(target, _config())


def test_扇区大小与分区配置不一致时拒绝(target):
    with pytest.raises(FlashError, match="扇区大小"):
        qualcomm_ufs.validate_bundle(target, _config(sector_size=512))


def test_系统盘不是整扇区时拒绝(target):
    (target / "image" / "raw.img").write_bytes(b"\0" * (SECTOR + 1))

    with pytest.raises(FlashError, match="整数倍"):
        qualcomm_ufs.validate_bundle(target, _config())


def test_固件xml不得引用子目录文件(target):
    _write_xml(target / qualcomm_ufs.FIRMWARE_DIR / "rawprogram1.xml",
               _program("xbl_a", "1", "../xbl.elf"))

    with pytest.raises(FlashError, match="非本目录"):
        qualcomm_ufs.validate_bundle(target, _config())


def test_整盘刷写在单个edl_ng会话写入固件与系统盘(target, monkeypatch):
    calls = []

    def run(cmd, cwd=None):
        stage = Path(cwd)
        calls.append((cmd, sorted(path.name for path in stage.iterdir())))
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr("builder.flash.strategy.subprocess.run", run)
    strategy = QualcommFlashStrategy()

    strategy.preflight(target, _config(), [])
    assert strategy.flash_whole_disk(Path("/tool/edl-ng"), target, _config()) is True

    [(cmd, staged)] = calls
    loader = target / qualcomm_ufs.FIRMWARE_DIR / "prog_firehose_ddr.elf"
    assert cmd == ["/tool/edl-ng", "--loader", str(loader), "--memory", "UFS", "rawprogram",
                   "rawprogram0.xml", "rawprogram1.xml", "rawprogram4.xml",
                   "patch1.xml", "patch4.xml"]
    assert {"rawprogram0.xml", "dtb.bin", qualcomm_ufs.SYSTEM_STAGED} <= set(staged)


def test_edl_ng失败时报告刷写失败(target, monkeypatch):
    monkeypatch.setattr(
        "builder.flash.strategy.subprocess.run",
        lambda cmd, cwd=None: type("Result", (), {"returncode": 1})())

    with pytest.raises(FlashError, match="rawprogram 刷写失败"):
        QualcommFlashStrategy().flash_whole_disk(Path("edl-ng"), target, _config())


def test_未声明ufs固件时保持write_sector整盘写(target, monkeypatch):
    calls = []
    monkeypatch.setattr(
        QualcommFlashStrategy, "write_system_image",
        lambda self, tool, raw, loader, memory="UFS": calls.append((raw, loader.name, memory)))
    config = _config(ufs_firmware=UfsFirmwareConfig(), board="radxa-dragon-q6a-like")

    QualcommFlashStrategy().preflight(target, config, [])
    assert QualcommFlashStrategy().flash_whole_disk(Path("edl-ng"), target, config) is True

    assert calls == [(target / "image" / "raw.img", "prog_firehose_ddr.elf", "UFS")]


def test_flash_config往返保留ufs固件且兼容旧清单(tmp_path):
    path = tmp_path / "flash-config.json"
    _config().to_json(path)
    assert FlashConfig.from_json(path).ufs_firmware == _config().ufs_firmware

    data = json.loads(path.read_text())
    del data["ufs_firmware"]
    path.write_text(json.dumps(data))
    assert FlashConfig.from_json(path).ufs_firmware == UfsFirmwareConfig()


def test_生成器从bootloader声明推导ufs固件清单():
    assert _ufs_firmware({"bootloader": {"edk2_firmware": {}}}) == UfsFirmwareConfig()
    assert _ufs_firmware({"bootloader": {
        "firehose_loader": "prog_firehose_ddr.elf",
        "ufs_rawprogram": ["rawprogram1.xml"],
        "ufs_patch": ["patch1.xml"],
    }}) == UfsFirmwareConfig("prog_firehose_ddr.elf", ["rawprogram1.xml"], ["patch1.xml"])


def test_ufs固件板拒绝spi_firmware(target):
    _config().to_json(target / "flash-config.json")

    with pytest.raises(FlashError, match="位于 UFS"):
        _cli_main(["run", "--target-dir", str(target), "--no-wait", "--spi-firmware"])
