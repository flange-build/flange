"""Tegra186 boot：kernel-dtb 分区内容与构建期 DTBO 合并。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from builder.platforms import nvidiategra186 as tegra
from builder.platforms.nvidiategra186.boot import Tegra186BootBuilder
from tests.builder.context import component_context

DTB = "tegra186-quill-p3310-1000-c03-00-base"


def _config(**overlays) -> dict:
    config = {
        "board": "nvidia-jetson-tx2",
        "platform": "nvidiategra186",
        "kernel": {"device_tree": {"directory": "", "name": DTB}},
    }
    if overlays:
        config["boot"] = {"overlays": {"intree": [], "vendor": [], "board": [], "package": [],
                                       "enabled": [], **overlays.get("sources", {})}}
        config["kernel"]["device_tree"]["build_overlays"] = overlays["build"]
    return config


def _builder(tmp_path, config, docker=None):
    builder = Tegra186BootBuilder(docker or MagicMock(), MagicMock())
    builder.context = component_context(tmp_path, config)
    return builder


def _kernel_dtb(builder):
    path = builder.context.target_dir / "kernel" / f"{DTB}.dtb"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xd0\x0d\xfe\xed kernel")
    return path


def test_without_overlays_publishes_kernel_dtb_unchanged(tmp_path):
    builder = _builder(tmp_path, _config())
    source = _kernel_dtb(builder)

    outputs = builder.build(_config())

    assert outputs["kernel_dtb"].name == "kernel-dtb.dtb"
    assert outputs["kernel_dtb"].read_bytes() == source.read_bytes()


def test_build_overlays_are_merged_with_fdtoverlay(tmp_path):
    config = _config(build=["uart.dtbo"], sources={"board": ["uart.dtbo"]})
    docker = MagicMock()
    builder = _builder(tmp_path, config, docker)
    base = _kernel_dtb(builder)
    overlay = builder.context.target_dir / "device-tree-overlay/overlays/uart.dtbo"
    overlay.parent.mkdir(parents=True)
    overlay.write_bytes(b"dtbo")

    outputs = builder.build(config)

    command = docker.run.call_args.args[0]
    assert command == ["fdtoverlay", "-i", str(base), "-o", str(outputs["kernel_dtb"]),
                       str(overlay)]


def test_intree_overlays_are_rejected(tmp_path):
    config = _config(build=["cam.dtbo"], sources={"intree": ["cam.dtbo"]})
    builder = _builder(tmp_path, config)
    _kernel_dtb(builder)

    with pytest.raises(ValueError, match="内核树内 overlay"):
        builder.build(config)


def test_missing_kernel_dtb_fails(tmp_path):
    with pytest.raises(FileNotFoundError, match="内核 DTB"):
        _builder(tmp_path, _config()).build(_config())


def test_factory_builds_boot():
    assert isinstance(tegra.create_builder("boot", None, None), Tegra186BootBuilder)
