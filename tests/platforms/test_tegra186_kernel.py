"""Tegra186 内核构建器：DTB 定位、配置覆盖与产物收集。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from builder.docker import BuildError
from builder.platforms import nvidiategra186 as tegra
from builder.platforms.nvidiategra186.kernel import Tegra186KernelBuilder

DTB = "tegra186-quill-p3310-1000-c03-00-base"
NESTED = "arch/arm64/boot/dts/_ddot_/_ddot_/_ddot_/_ddot_/nvidia/platform/t18x/quill/kernel-dts"


def _config(overrides=None) -> dict:
    kernel = {"defconfig": ["tegra_defconfig"], "device_tree": {"directory": "", "name": DTB}}
    if overrides:
        kernel["config"] = overrides
    return {"platform": "nvidiategra186", "board": "nvidia-jetson-tx2", "kernel": kernel}


def _touch(root, relative):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xd0\x0d\xfe\xed")
    return path


def test_factory_builds_kernel_without_side_effects():
    builder = tegra.create_builder("kernel", None, None)
    assert isinstance(builder, Tegra186KernelBuilder)


def test_nested_ddot_dtb_is_collected(tmp_path):
    dtb = _touch(tmp_path, f"{NESTED}/{DTB}.dtb")

    outputs = Tegra186KernelBuilder(MagicMock(), MagicMock()).collect(tmp_path, _config())

    assert outputs["dtb"] == dtb
    assert outputs["image"] == tmp_path / "arch/arm64/boot/Image"
    assert outputs["config"] == tmp_path / ".config"


def test_identical_flat_copy_is_accepted(tmp_path):
    nested = _touch(tmp_path, f"{NESTED}/{DTB}.dtb")
    _touch(tmp_path, f"arch/arm64/boot/dts/{DTB}.dtb")

    outputs = Tegra186KernelBuilder(MagicMock(), MagicMock()).collect(tmp_path, _config())

    assert outputs["dtb"].read_bytes() == nested.read_bytes()


@pytest.mark.parametrize("copies", [0, 2])
def test_dtb_missing_or_divergent_copies_fail(tmp_path, copies):
    for index in range(copies):
        _touch(tmp_path, f"arch/arm64/boot/dts/copy{index}/{DTB}.dtb").write_bytes(bytes([index]))

    with pytest.raises(BuildError, match="内容一致"):
        Tegra186KernelBuilder(MagicMock(), MagicMock()).collect(tmp_path, _config())


def _make_calls(docker):
    return [call.args[0] for call in docker.run.call_args_list]


def test_configure_without_overrides_only_runs_defconfig(tmp_path, monkeypatch):
    monkeypatch.setattr("builder.filesystem.require_case_sensitive", lambda path: None)
    docker = MagicMock()

    Tegra186KernelBuilder(docker, MagicMock()).configure(tmp_path, _config())

    calls = _make_calls(docker)
    assert len(calls) == 1 and calls[0][-1] == "tegra_defconfig"
    assert "LOCALVERSION=" in calls[0]


def test_configure_appends_overrides_then_olddefconfig(tmp_path, monkeypatch):
    monkeypatch.setattr("builder.filesystem.require_case_sensitive", lambda path: None)
    docker = MagicMock()

    Tegra186KernelBuilder(docker, MagicMock()).configure(
        tmp_path, _config({"CONFIG_USB_CONFIGFS_F_HID": "y"})
    )

    calls = _make_calls(docker)
    assert calls[0][-1] == "tegra_defconfig"
    assert calls[1] == ["sh", "-c", "cat arch/arm64/configs/flange_overrides.config >> .config"]
    assert calls[2][-1] == "olddefconfig"
    fragment = tmp_path / "arch/arm64/configs/flange_overrides.config"
    assert "CONFIG_USB_CONFIGFS_F_HID=y" in fragment.read_text()
