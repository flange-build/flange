"""Rockchip SPI NAND MTD 刷写包、preflight 与具名 DI 流程测试。"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from builder.flash import (
    DeviceInfo,
    FlashConfig,
    FlashConfigGenerator,
    FlashError,
    FlashExecutor,
    FlashPartition,
    RockchipFlashStrategy,
)
from builder.platforms.rockchip.image import RockchipImageBuilder


class FakeCache:
    def __init__(self, target_dir: Path):
        self.target_dir = target_dir


class FdtDocker:
    """MTD image route 只允许调用 fdtget，不允许 GPT/truncate/dd。"""

    def __init__(self, bootargs="ubi.mtd=5 root=ubi0:rootfs rootfstype=ubifs"):
        self.bootargs = bootargs
        self.commands: list[list[str]] = []

    def run(self, cmd: list[str], **kwargs):
        self.commands.append(list(cmd))
        if cmd[0] != "fdtget":
            raise AssertionError(f"MTD image route 不应调用 {cmd[0]}")
        return SimpleNamespace(stdout=self.bootargs + "\n")


def _write_parameter(tmp_path: Path) -> Path:
    parameter = tmp_path / "parameter.txt"
    parameter.write_text(
        "TYPE: MTD\n"
        "CMDLINE:mtdparts=rk29xxnand:"
        "0x1000@0x0(security),0x2000@0x1000(uboot),"
        "0x1000@0x3000(misc),0x10000@0x4000(boot),"
        "0x2000@0x14000(amp),-@0x16000(rootfs)\n"
    )
    return parameter


def _config(tmp_path: Path) -> dict:
    return {
        "platform": "rockchip",
        "flash_tool": "upgrade_tool",
        "board": "atk-rk3506b",
        "product": "default",
        "variant": "release",
        "architecture": {
            "userspace": "armhf", "kernel": "arm", "bootloader": "arm",
        },
        "storage": {"type": "spinand", "size": "512M"},
        "kernel": {
            "image": "zImage",
            "device_tree": {"directory": "", "name": "rk3506b-test"},
            "boot_format": "fit",
            "boot_its": "boot.its",
        },
        "partitions": {
            "format": "mtd",
            "parameter": str(_write_parameter(tmp_path)),
        },
        "rootfs": {
            "image_format": "ubi",
            "ubi": {
                "min_io_size": 2048,
                "peb_size": 131072,
                "subpage_size": 2048,
                "vid_hdr_offset": 2048,
                "leb_size": 126976,
                "max_leb_count": 3500,
                "volume_size": "400M",
                "reserved_pebs": 20,
                "mtd_index": 5,
            },
        },
        "recovery": {"enabled": False},
        "amp": {
            "enabled": True,
            "mode": "rt-thread",
            "soc_project": "rk3506",
            "max_image_size": "1M",
            "memory": {
                "cpu": 2,
                "cpu_base": 0x03E00000,
                "dram_size": 0x00100000,
                "sram_base": 0xFFF80000,
                "sram_size": 0x0000C000,
                "shmem_base": 0x03B00000,
                "shmem_size": 0x00100000,
                "rpmsg_base": 0x03C00000,
                "rpmsg_size": 0x00200000,
            },
        },
    }


def _gpt_spinand_config(tmp_path: Path) -> dict:
    config = _config(tmp_path)
    config["partitions"] = {
        "format": "gpt",
        "sector_size": 512,
        "entries": [
            {"name": "idbloader", "offset": "0x40", "size": "0x2000",
             "type": "raw"},
            {"name": "uboot", "offset": "0x4000", "size": "0x2000",
             "type": "raw"},
            {"name": "boot", "offset": "0x8000", "size": "0x20000",
             "type": "ext4"},
            {"name": "recovery", "offset": "0x28000", "size": "0x800",
             "type": "ext4"},
            {"name": "amp", "offset": "0x28800", "size": "0x8000",
             "type": "ext4"},
            {"name": "rootfs", "offset": "0x30800", "size": "414M",
             "type": "ext4"},
        ],
    }
    config["rootfs"]["ubi"].update({
        "max_leb_count": 4096,
        "volume_size": "409878528B",
        "reserved_pebs": 82,
    })
    return config


def _prepare_artifacts(target_dir: Path, *, amp_size=4096) -> None:
    artifacts = {
        "bootloader/miniloader.bin": b"loader",
        "bootloader/idbloader.img": b"idb",
        "bootloader/u-boot.itb": b"uboot",
        "boot/boot.img": b"boot",
        "amp/amp.img": b"A" * amp_size,
        "rootfs/rootfs.ubi": b"UBI#",
        "kernel/rk3506b-test.dtb": b"dtb",
    }
    for relative, data in artifacts.items():
        path = target_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def test_mtd_image_builds_manifest_without_raw_gpt_or_dd(tmp_path):
    config = _config(tmp_path)
    target_dir = tmp_path / "target"
    _prepare_artifacts(target_dir)
    docker = FdtDocker()
    builder = RockchipImageBuilder(docker=docker, source=None)
    builder.cache = FakeCache(target_dir)

    outputs = builder.build(config)

    manifest = json.loads(outputs["bundle"].read_text())
    assert manifest["format"] == "mtd"
    assert manifest["rootfs_mtd_index"] == 5
    assert [part["name"] for part in manifest["partitions"]] == [
        "uboot", "boot", "amp", "rootfs"]
    assert manifest["bootloader_artifacts"] == [
        "bootloader/miniloader.bin",
        "bootloader/idbloader.img",
        "bootloader/u-boot.itb",
    ]
    assert outputs["parameter"].name == "parameter.txt"
    assert not (builder._work_dir / "raw.img").exists()
    assert [cmd[0] for cmd in docker.commands] == ["fdtget"]


def test_mtd_image_rejects_dtb_ubi_index_mismatch(tmp_path):
    config = _config(tmp_path)
    target_dir = tmp_path / "target"
    _prepare_artifacts(target_dir)
    builder = RockchipImageBuilder(
        docker=FdtDocker("ubi.mtd=4 root=ubi0:rootfs"), source=None)
    builder.cache = FakeCache(target_dir)

    with pytest.raises(Exception, match="ubi.mtd=4"):
        builder.build(config)


def test_gpt_spinand_builds_named_bundle_without_raw_image(tmp_path):
    config = _gpt_spinand_config(tmp_path)
    target_dir = tmp_path / "target"
    _prepare_artifacts(target_dir)
    docker = FdtDocker()
    builder = RockchipImageBuilder(docker=docker, source=None)
    builder.cache = FakeCache(target_dir)
    stale_raw = target_dir / "image/raw.img"
    stale_raw.parent.mkdir(parents=True)
    stale_raw.write_bytes(b"stale raw image")

    outputs = builder.build(config)

    manifest = json.loads(outputs["bundle"].read_text())
    assert manifest["format"] == "gpt"
    assert manifest["storage_type"] == "spinand"
    assert manifest["rootfs_mtd_index"] == 5
    assert outputs["parameter"].read_text().startswith("FIRMWARE_VER: 1.0\n")
    assert not (builder._work_dir / "raw.img").exists()
    assert not stale_raw.exists()
    assert [cmd[0] for cmd in docker.commands] == ["fdtget"]


def test_gpt_spinand_rejects_dtb_ubi_index_mismatch(tmp_path):
    config = _gpt_spinand_config(tmp_path)
    target_dir = tmp_path / "target"
    _prepare_artifacts(target_dir)
    builder = RockchipImageBuilder(
        docker=FdtDocker("ubi.mtd=4 root=ubi0:rootfs"), source=None)
    builder.cache = FakeCache(target_dir)

    with pytest.raises(Exception, match="ubi.mtd=4"):
        builder.build(config)


def test_flash_config_generator_uses_parameter_and_ubi_mapping(tmp_path):
    config = _config(tmp_path)
    target_dir = tmp_path / "target"

    FlashConfigGenerator().generate(config, target_dir)
    flash = FlashConfig.from_json(target_dir / "flash-config.json")

    assert flash.partition_format == "mtd"
    assert flash.storage == ""
    assert flash.storage_size == "512M"
    assert flash.parameter == "parameter.txt"
    assert flash.rootfs_mtd_index == 5
    by_name = {part.name: part for part in flash.partitions}
    assert list(by_name) == ["uboot", "boot", "amp", "rootfs"]
    assert by_name["rootfs"].image == "rootfs/rootfs.ubi"
    assert by_name["rootfs"].type == "ubi"
    assert by_name["amp"].image == "amp/amp.img"
    assert (target_dir / "parameter.txt").read_text() == (
        Path(config["partitions"]["parameter"]).read_text())


def test_gpt_spinand_generates_parameter_and_uses_named_di(tmp_path):
    config = _gpt_spinand_config(tmp_path)
    target_dir = tmp_path / "target"
    _prepare_artifacts(target_dir)
    FlashConfigGenerator().generate(config, target_dir)
    flash = FlashConfig.from_json(target_dir / "flash-config.json")
    strategy = RockchipFlashStrategy()

    assert flash.partition_format == "gpt"
    assert flash.storage_type == "spinand"
    assert flash.parameter == "parameter.txt"
    assert flash.rootfs_mtd_index == 5
    assert "idbloader" not in {part.name for part in flash.partitions}
    assert (target_dir / "parameter.txt").read_text().startswith(
        "FIRMWARE_VER: 1.0\n")
    strategy.preflight(target_dir, flash, flash.partitions)

    amp = next(part for part in flash.partitions if part.name == "amp")
    with patch("builder.flash.subprocess.run") as run:
        strategy.write_named_partition(
            Path("upgrade_tool"), amp, target_dir / amp.image, flash)
    assert run.call_args.args[0][1:3] == ["DI", "-amp"]


def _flash_target(tmp_path: Path) -> tuple[Path, FlashConfig]:
    config = _config(tmp_path)
    target_dir = tmp_path / "target"
    _prepare_artifacts(target_dir)
    FlashConfigGenerator().generate(config, target_dir)
    return target_dir, FlashConfig.from_json(target_dir / "flash-config.json")


def test_spinand_preflight_checks_all_images_before_device_write(tmp_path):
    target_dir, flash = _flash_target(tmp_path)
    (target_dir / "amp/amp.img").unlink()
    strategy = RockchipFlashStrategy()

    with patch("builder.flash.subprocess.run") as run:
        with pytest.raises(FlashError, match="amp.*镜像不存在"):
            strategy.preflight(target_dir, flash, flash.partitions)
    run.assert_not_called()


def test_spinand_preflight_rejects_stale_idbloader_manifest(tmp_path):
    config = _gpt_spinand_config(tmp_path)
    target_dir = tmp_path / "target"
    _prepare_artifacts(target_dir)
    FlashConfigGenerator().generate(config, target_dir)
    flash = FlashConfig.from_json(target_dir / "flash-config.json")
    flash.partitions.insert(0, FlashPartition(
        name="idbloader",
        offset="0x40",
        type="raw",
        image="bootloader/idbloader.img",
    ))

    with patch("builder.flash.subprocess.run") as run:
        with pytest.raises(FlashError, match="旧版构建产物.*build image -f"):
            RockchipFlashStrategy().preflight(
                target_dir, flash, flash.partitions)
    run.assert_not_called()


def test_spinand_preflight_rejects_parameter_digest_mismatch(tmp_path):
    target_dir, flash = _flash_target(tmp_path)
    parameter = target_dir / "parameter.txt"
    parameter.write_text(parameter.read_text().replace("rootfs", "rootbad"))

    with pytest.raises(FlashError, match="摘要不一致"):
        RockchipFlashStrategy().preflight(
            target_dir, flash, flash.partitions)


def test_spinand_preflight_rejects_layout_drift_even_with_new_digest(tmp_path):
    config = _gpt_spinand_config(tmp_path)
    target_dir = tmp_path / "target"
    _prepare_artifacts(target_dir)
    FlashConfigGenerator().generate(config, target_dir)
    flash = FlashConfig.from_json(target_dir / "flash-config.json")
    parameter = target_dir / "parameter.txt"
    parameter.write_text(parameter.read_text().replace(
        "0x000cf000@0x00030800(rootfs)",
        "0x000ce800@0x00031000(rootfs)",
    ))
    flash.parameter_sha256 = hashlib.sha256(
        parameter.read_bytes()).hexdigest()

    with pytest.raises(FlashError, match="rootfs.*布局不一致"):
        RockchipFlashStrategy().preflight(
            target_dir, flash, flash.partitions)


def test_spinand_full_flash_order_is_ul_parameter_named_parts_without_ssd(
    tmp_path,
):
    config = _gpt_spinand_config(tmp_path)
    target_dir = tmp_path / "target"
    _prepare_artifacts(target_dir)
    FlashConfigGenerator().generate(config, target_dir)
    flash = FlashConfig.from_json(target_dir / "flash-config.json")
    strategy = RockchipFlashStrategy()

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    strategy.preflight(target_dir, flash, flash.partitions)
    with patch("builder.flash.subprocess.run", side_effect=fake_run) as run, \
         patch("builder.flash.time.sleep"):
        strategy.pre_flash_all(
            Path("upgrade_tool"), target_dir, flash,
            DeviceInfo("rockchip", "maskrom", ""),
        )
        assert strategy.flash_whole_disk(
            Path("upgrade_tool"), target_dir, flash) is True

    commands = [call.args[0] for call in run.call_args_list]
    rendered = [" ".join(map(str, cmd)) for cmd in commands]
    assert commands[0][1:3] == ["DB", str(
        target_dir / "bootloader/miniloader.bin")]
    assert commands[1][1] == "UL"
    assert commands[1][2] == str(target_dir / "bootloader/miniloader.bin")
    assert commands[1][3] == "-noreset"
    assert commands[2][1:3] == ["DI", "-p"]
    assert not any(len(cmd) > 1 and cmd[1] == "SSD" for cmd in commands)
    assert "DI -u" in rendered[3]
    assert "DI -b" in rendered[4]
    assert "DI -amp" in rendered[5]
    assert "DI -rootfs" in rendered[6]


def test_explicit_spinand_storage_selector_still_fails_when_missing(tmp_path):
    target_dir, flash = _flash_target(tmp_path)
    flash.storage = "SPINAND"
    strategy = RockchipFlashStrategy()

    def fake_run(cmd, **kwargs):
        if cmd[1:] == ["SSD"]:
            return SimpleNamespace(
                returncode=0, stdout="No=9\tSATA(*)\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with patch("builder.flash.subprocess.run", side_effect=fake_run) as run, \
         patch("builder.flash.time.sleep"):
        with pytest.raises(FlashError, match="未找到存储 'SPINAND'"):
            strategy.pre_flash(
                Path("upgrade_tool"), target_dir, flash,
                DeviceInfo("rockchip", "maskrom", ""),
            )
    commands = [call.args[0] for call in run.call_args_list]
    assert not any(len(cmd) > 1 and cmd[1] == "DI" for cmd in commands)


def test_spinand_loader_mode_skips_db_and_ssd(tmp_path):
    target_dir, flash = _flash_target(tmp_path)
    strategy = RockchipFlashStrategy()

    with patch("builder.flash.subprocess.run") as run:
        strategy.pre_flash(
            Path("upgrade_tool"), target_dir, flash,
            DeviceInfo("rockchip", "loader", ""),
        )

    run.assert_not_called()


def test_spinand_write_gpt_waits_for_di_parameter_even_without_storage(
    tmp_path,
):
    target_dir, flash = _flash_target(tmp_path)
    strategy = RockchipFlashStrategy()

    with patch("builder.flash.subprocess.run") as run:
        strategy.write_gpt(Path("upgrade_tool"), target_dir, flash)

    run.assert_not_called()


@pytest.mark.parametrize(
    "requested,expected_flag",
    [
        ("kernel", "-b"),
        ("rootfs", "-rootfs"),
        ("amp", "-amp"),
    ],
)
def test_mtd_single_component_uses_only_named_partition(
    tmp_path,
    requested,
    expected_flag,
):
    target_dir, _ = _flash_target(tmp_path)
    strategy = RockchipFlashStrategy()
    with patch("builder.flash.get_flash_strategy", return_value=strategy):
        executor = FlashExecutor(target_dir, tmp_path)
    with patch.object(strategy, "find_tool", return_value=Path("upgrade_tool")), \
         patch.object(strategy, "pre_flash"), \
         patch("builder.flash.subprocess.run") as run:
        executor.flash_partition(requested, no_wait=True, no_reboot=True)

    commands = [call.args[0] for call in run.call_args_list]
    assert len(commands) == 1
    assert commands[0][1:3] == ["DI", expected_flag]
    assert all("-p" not in cmd for cmd in commands)


@pytest.mark.parametrize("requested", ["bootloader", "uboot"])
def test_spinand_bootloader_component_updates_loader_then_uboot(
    tmp_path,
    requested,
):
    target_dir, _ = _flash_target(tmp_path)
    strategy = RockchipFlashStrategy()

    def fake_run(cmd, **kwargs):
        if cmd[1:] == ["LD"]:
            return SimpleNamespace(
                returncode=0,
                stdout="List of rockusb connected(1) DevNo=1 Mode=Loader\n",
                stderr="",
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with patch("builder.flash.get_flash_strategy", return_value=strategy):
        executor = FlashExecutor(target_dir, tmp_path)
    with patch.object(strategy, "find_tool", return_value=Path("upgrade_tool")), \
         patch("builder.flash.subprocess.run", side_effect=fake_run) as run, \
         patch("builder.flash.time.sleep"):
        executor.flash_partition(
            requested, no_wait=True, no_reboot=True)

    commands = [call.args[0] for call in run.call_args_list]
    assert commands[0][1:] == ["LD"]
    assert commands[1] == [
        "upgrade_tool",
        "UL",
        str(target_dir / "bootloader/miniloader.bin"),
        "-noreset",
    ]
    assert commands[2][1:3] == ["DI", "-u"]
    assert len(commands) == 3
