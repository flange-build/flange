"""Tegra186 image：tegraflash 刷写包组装、分区布局与 system.img 生成。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from builder.docker import BuildError
from builder.flash.tegra import validate_bundle
from builder.platforms import nvidiategra186 as tegra
from builder.platforms.nvidiategra186.image import Tegra186ImageBuilder
from tests.builder.context import component_context
from tests.platforms.tegra186_fixtures import DTB, fake_mksparse, image_config, upstream


def _builder(tmp_path, config):
    docker = MagicMock()
    docker.run.side_effect = fake_mksparse
    builder = Tegra186ImageBuilder(docker, MagicMock())
    builder.context = component_context(tmp_path, config)
    return builder


def _commands(builder):
    return [call.args[0] for call in builder.docker.run.call_args_list]


def test_bundle_contains_rendered_layout_and_valid_manifest(tmp_path):
    config = image_config()
    builder = _builder(tmp_path, config)
    upstream(builder.context.target_dir)

    bundle = builder.build(config)["bundle"]

    layout = (bundle / "flash.xml").read_text()
    assert "<size> 1073741824 </size>" in layout
    assert f"<filename> kernel_{DTB}.dtb </filename>" in layout
    assert "RECFILE" not in layout and "<filename> recovery" not in layout
    assert (bundle / f"kernel_{DTB}.dtb").read_bytes() == b"\xd0\x0d\xfe\xed dtb"
    assert (bundle / "tos.img").is_symlink()
    manifest = validate_bundle(bundle)
    assert [entry["name"] for entry in manifest["partitions"]] == [
        "cpu-bootloader", "cpu-bootloader_b", "APP", "kernel", "kernel-dtb",
        "kernel-bootctrl", "VER",
    ]
    protected = {entry["name"] for entry in manifest["partitions"] if entry["protected"]}
    assert "APP" not in protected and "kernel-dtb" not in protected and "kernel" in protected
    assert manifest["identity"] == config["bootloader"]["tegraflash"]["identity"]


def test_system_image_is_grown_to_app_size_then_sparsed(tmp_path):
    config = image_config()
    builder = _builder(tmp_path, config)
    upstream(builder.context.target_dir)

    builder.build(config)

    commands = _commands(builder)
    names = [command[0] for command in commands]
    assert names == ["cp", "e2fsck", "truncate", "resize2fs", "./mksparse", "rm"]
    assert commands[2][2] == str(1024 ** 3)
    assert commands[4][1] == "--fillpattern=0"


def test_version_file_uses_bsp_release_and_identity(tmp_path):
    config = image_config()
    builder = _builder(tmp_path, config)
    upstream(builder.context.target_dir)

    bundle = builder.build(config)["bundle"]

    lines = (bundle / "emmc_bootblob_ver.txt").read_text().splitlines()
    assert lines[:3] == ["NV3", "# R32 , REVISION: 7.6", "BOARDID=3310 BOARDSKU=1000 FAB=B02"]
    assert lines[4].startswith("BYTES:")


def test_rootfs_larger_than_app_fails(tmp_path):
    config = image_config()
    config["partitions"]["entries"][0]["size"] = "1M"
    builder = _builder(tmp_path, config)
    upstream(builder.context.target_dir, rootfs_bytes=2 * 1024 * 1024)

    with pytest.raises(BuildError, match="大于 APP 分区"):
        builder.build(config)


def test_generated_tokens_cannot_be_declared(tmp_path):
    config = image_config()
    config["bootloader"]["tegraflash"]["layout_tokens"]["APPFILE"] = "other.img"
    builder = _builder(tmp_path, config)
    upstream(builder.context.target_dir)

    with pytest.raises(ValueError, match="APPFILE"):
        builder.build(config)


def test_manifest_records_flash_args(tmp_path):
    config = image_config()
    builder = _builder(tmp_path, config)
    upstream(builder.context.target_dir)

    bundle = builder.build(config)["bundle"]

    args = json.loads((bundle / "manifest.json").read_text())["args"]
    assert args[:2] == ["--bl", "nvtboot_recovery_cpu.bin"]
    assert args[args.index("--cfg") + 1] == "flash.xml"
    assert args[-1] == "mb2_bootloader nvtboot_recovery.bin; bpmp_fw bpmp.bin"


def test_factory_builds_image():
    assert isinstance(tegra.create_builder("image", None, None), Tegra186ImageBuilder)
