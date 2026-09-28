"""Tegra186（Jetson TX2）平台契约：产物声明与构建工厂。"""

from __future__ import annotations

from pathlib import Path

import pytest

from builder.component_plan import output_contract
from builder.platforms import nvidiategra186 as tegra
from builder.workspace import Target, WorkspaceContext

DTB = "tegra186-quill-p3310-1000-c03-00-base"


def _config(**extra) -> dict:
    return {
        "platform": "nvidiategra186",
        "kernel": {"device_tree": {"directory": "", "name": DTB}},
        **extra,
    }


def _context(tmp_path: Path) -> WorkspaceContext:
    return WorkspaceContext(
        tmp_path, tmp_path, tmp_path / ".build",
        Target("nvidia-jetson-tx2", "default", "release"),
    )


def test_kernel_publishes_image_dtb_modules_and_config(tmp_path):
    outputs = {spec.name: spec for spec in tegra.required_artifacts("kernel", tmp_path, _config())}

    assert outputs["image"].path == tmp_path / "Image"
    assert outputs["dtb"].path == tmp_path / f"{DTB}.dtb"
    assert outputs["modules"].kind == "tree"
    assert outputs["config"].path == tmp_path / "config"
    assert "headers" not in outputs


def test_bootloader_contract_requires_flash_tree_and_generated_files(tmp_path):
    outputs = {spec.name: spec for spec in tegra.required_artifacts("bootloader", tmp_path, _config())}

    tree = tmp_path / "tegraflash"
    assert outputs["tegraflash"].kind == "tree"
    assert {outputs[name].path for name in ("tegraflash_py", "uboot", "bootctrl")} == {
        tree / "tegraflash.py", tree / "boot.img", tree / "kernel_bootctrl.bin",
    }


def test_boot_publishes_only_kernel_dtb(tmp_path):
    outputs = tegra.required_artifacts("boot", tmp_path, _config())

    assert [spec.path for spec in outputs] == [tmp_path / "kernel-dtb.dtb"]


def test_image_contract_adds_flash_config(tmp_path):
    context = _context(tmp_path)
    outputs = {spec.name: spec for spec in output_contract("image", _config(), context)}

    bundle = context.target_dir / "image" / "tegraflash-bundle"
    assert outputs["bundle"].path == bundle
    assert outputs["manifest"].path == bundle / "manifest.json"
    assert outputs["flash-config"].path == context.target_dir / "flash-config.json"


def test_rootfs_uses_default_contract(tmp_path):
    assert tegra.required_artifacts("rootfs", tmp_path, _config()) is None


def test_recovery_is_not_supported():
    with pytest.raises(ValueError, match="不支持组件"):
        tegra.create_builder("recovery", None, None)
