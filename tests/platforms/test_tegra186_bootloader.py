"""Tegra186 bootloader：BSP 安全解包、刷写目录组装与 flash.sh 生成文件。"""

from __future__ import annotations

import io
import tarfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from builder.platforms import nvidiategra186 as tegra
from builder.platforms.nvidiategra186.bootloader import (
    Tegra186BootloaderBuilder,
    extract_bsp,
    root_device,
    stage_flash_tree,
)
from tests.builder.context import component_context

ROOT = "Linux_for_Tegra"
KERNEL_ARGS = "root=/dev/mmcblk0p1 rw rootwait rootfstype=ext4 console=ttyS0,115200n8"


def _tegraflash() -> dict:
    return {
        "bl": "nvtboot_recovery_cpu.bin",
        "applet": "mb1_recovery_prod.bin",
        "layout_template": "bootloader/t186ref/cfg/flash_l4t_t186.xml",
        "bct_configs": {"dev_params": "emmc.cfg"},
        "bins": [
            {"type": "tlk", "file": "tos-trusty.img"},
            {"type": "bootloader_dtb", "file": "board.dtb"},
        ],
        "extra_files": ["bootloader/t186ref/BCT/emmc.cfg", "kernel/dtb/board.dtb"],
        "uboot": "bootloader/t186ref/p2771-0000/500/u-boot.bin",
    }


def _add(archive: tarfile.TarFile, name: str, data: bytes = b"x", **fields) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    for key, value in fields.items():
        setattr(info, key, value)
    archive.addfile(info, io.BytesIO(data) if info.isfile() else None)


def _bsp(path: Path, extra_members=()) -> Path:
    with tarfile.open(path, "w:bz2") as archive:
        for name in (
            "bootloader/tegraflash.py", "bootloader/mkbootimg", "bootloader/tos-trusty.img",
            "bootloader/nvtboot_recovery_cpu.bin", "bootloader/mb1_recovery_prod.bin",
            "bootloader/t186ref/BCT/emmc.cfg", "bootloader/t186ref/cfg/flash_l4t_t186.xml",
            "bootloader/t186ref/p2771-0000/500/u-boot.bin", "nv_tegra/bsp_version",
            "kernel/dtb/board.dtb", "kernel/Image",
        ):
            _add(archive, f"{ROOT}/{name}")
        _add(archive, f"{ROOT}/bootloader/tos.img", type=tarfile.SYMTYPE, linkname="tos-trusty.img")
        for member in extra_members:
            _add(archive, **member)
    return path


def _extra() -> list[str]:
    tegraflash = _tegraflash()
    return [*tegraflash["extra_files"], tegraflash["uboot"], "nv_tegra/bsp_version"]


def test_extract_takes_bootloader_tree_and_named_files_only(tmp_path):
    root = extract_bsp(_bsp(tmp_path / "bsp.tbz2"), tmp_path / "out", _extra())

    assert (root / "bootloader/t186ref/BCT/emmc.cfg").is_file()
    assert (root / "kernel/dtb/board.dtb").is_file()
    assert (root / "bootloader/tos.img").is_symlink()
    assert not (root / "kernel/Image").exists()


@pytest.mark.parametrize(
    "member",
    [
        {"name": f"{ROOT}/bootloader/../../escape"},
        {"name": f"{ROOT}/bootloader/passwd", "type": tarfile.SYMTYPE, "linkname": "/etc/passwd"},
        {"name": f"{ROOT}/bootloader/null", "type": tarfile.CHRTYPE},
    ],
)
def test_extract_rejects_unsafe_members(tmp_path, member):
    archive = _bsp(tmp_path / "bsp.tbz2", [member])

    with pytest.raises(ValueError, match="不安全"):
        extract_bsp(archive, tmp_path / "out", _extra())


def test_extract_reports_missing_named_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="kernel/dtb/missing.dtb"):
        extract_bsp(_bsp(tmp_path / "bsp.tbz2"), tmp_path / "out", ["kernel/dtb/missing.dtb"])


def test_stage_flattens_files_and_keeps_links(tmp_path):
    root = extract_bsp(_bsp(tmp_path / "bsp.tbz2"), tmp_path / "out", _extra())
    tree = tmp_path / "tree"

    stage_flash_tree(root, tree, _tegraflash())

    for name in ("tegraflash.py", "emmc.cfg", "board.dtb", "flash_l4t_t186.xml", "bsp_version"):
        assert (tree / name).is_file(), name
    assert (tree / "tos.img").readlink() == Path("tos-trusty.img")
    assert not (tree / "t186ref").exists()


def test_stage_reports_unresolved_reference(tmp_path):
    root = extract_bsp(_bsp(tmp_path / "bsp.tbz2"), tmp_path / "out", _extra())
    tegraflash = _tegraflash()
    tegraflash["bct_configs"]["sdram_config"] = "sdram.cfg"

    with pytest.raises(FileNotFoundError, match="bct_configs.sdram_config=sdram.cfg"):
        stage_flash_tree(root, tmp_path / "tree", tegraflash)


def test_stage_rejects_name_collision(tmp_path):
    root = extract_bsp(_bsp(tmp_path / "bsp.tbz2"), tmp_path / "out",
                       [*_extra(), "bootloader/t186ref/p2771-0000/500/u-boot.bin"])
    tegraflash = _tegraflash()
    tegraflash["extra_files"].append("bootloader/tegraflash.py")

    with pytest.raises(ValueError, match="同名"):
        stage_flash_tree(root, tmp_path / "tree", tegraflash)


def test_root_device_comes_from_kernel_args():
    assert root_device(KERNEL_ARGS) == "mmcblk0p1"
    with pytest.raises(ValueError, match="root=/dev"):
        root_device("root=PARTLABEL=APP rw")


def _config() -> dict:
    return {
        "board": "nvidia-jetson-tx2",
        "bootloader": {
            "l4t_bsp": {"url": "https://example.test/l4t.tbz2", "sha256": "0" * 64},
            "tegraflash": _tegraflash(),
        },
        "boot": {"kernel_args": KERNEL_ARGS},
    }


def test_build_wraps_uboot_like_flash_sh(tmp_path):
    source, docker = MagicMock(), MagicMock()
    source.ensure_prebuilt_image.return_value = _bsp(tmp_path / "bsp.tbz2")
    builder = Tegra186BootloaderBuilder(docker, source)
    builder.context = component_context(tmp_path, _config())

    outputs = builder.build(_config())

    tree = outputs["tegraflash"]
    assert (tree / "kernel_bootctrl.bin").read_bytes() == bytes(20)
    command = docker.run.call_args.args[0]
    assert command[0] == "./mkbootimg"
    assert command[command.index("--ramdisk") + 1] == "/dev/null"
    assert command[command.index("--board") + 1] == "mmcblk0p1"
    assert command[command.index("--cmdline") + 1] == f"{KERNEL_ARGS} "
    assert command[command.index("--kernel") + 1].endswith("500/u-boot.bin")
    assert docker.run.call_args.kwargs["cwd"] == str(tree)


def test_digest_failure_stops_before_extraction(tmp_path):
    source = MagicMock()
    source.ensure_prebuilt_image.side_effect = ValueError("sha256 不匹配")
    builder = Tegra186BootloaderBuilder(MagicMock(), source)
    builder.context = component_context(tmp_path, _config())

    with pytest.raises(ValueError, match="sha256"):
        builder.build(_config())
    assert not list(tmp_path.rglob("tegraflash.py"))


def test_factory_builds_bootloader():
    assert isinstance(tegra.create_builder("bootloader", None, None), Tegra186BootloaderBuilder)
