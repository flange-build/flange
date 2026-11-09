"""Tegra186 rootfs：L4T preinst 标记与 APP 分区启动文件。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from builder.docker import BuildError
from builder.platforms import nvidiategra186 as tegra
from builder.platforms.nvidiategra186.rootfs import L4T_PREINSTALL_MARKER, Tegra186RootfsBuilder
from builder.rootfs import RootfsBuilder
from tests.builder.context import component_context

KERNEL_ARGS = "root=/dev/mmcblk0p1 rw rootwait console=ttyS0,115200n8"


def _config() -> dict:
    return {"board": "nvidia-jetson-tx2", "platform": "nvidiategra186",
            "boot": {"kernel_args": KERNEL_ARGS}}


def _builder(tmp_path, docker=None):
    builder = Tegra186RootfsBuilder(docker or MagicMock(), MagicMock())
    builder.context = component_context(tmp_path, _config())
    return builder


def test_marker_exists_only_during_phase2(tmp_path, monkeypatch):
    rootfs = tmp_path / "rootfs"
    seen = []
    monkeypatch.setattr(
        RootfsBuilder, "_build_phase2",
        lambda self, root, config: seen.append((root / L4T_PREINSTALL_MARKER).is_file()),
    )

    _builder(tmp_path)._build_phase2(rootfs, _config())

    assert seen == [True]
    assert not (rootfs / L4T_PREINSTALL_MARKER).exists()


def test_marker_is_removed_when_phase2_fails(tmp_path, monkeypatch):
    rootfs = tmp_path / "rootfs"

    def fail(self, root, config):
        raise BuildError("apt-get install 失败")

    monkeypatch.setattr(RootfsBuilder, "_build_phase2", fail)

    with pytest.raises(BuildError):
        _builder(tmp_path)._build_phase2(rootfs, _config())
    assert not (rootfs / L4T_PREINSTALL_MARKER).exists()


def test_post_customize_installs_kernel_and_extlinux(tmp_path):
    rootfs = tmp_path / "rootfs"
    (rootfs / "boot").mkdir(parents=True)
    (rootfs / "boot/initrd").write_bytes(b"initrd")
    docker = MagicMock()
    builder = _builder(tmp_path, docker)

    builder._post_customize(rootfs, _config())

    image = builder.context.target_dir / "kernel" / "Image"
    docker.run_privileged.assert_called_once_with(["cp", str(image), str(rootfs / "boot/Image")])
    lines = (rootfs / "boot/extlinux/extlinux.conf").read_text().splitlines()
    assert "  kernel /boot/Image" in lines
    assert "  initrd /boot/initrd" in lines
    assert f"  append ${{cbootargs}} {KERNEL_ARGS}" in lines
    assert not any(line.strip().startswith(("fdt", "devicetree")) for line in lines)


def test_missing_l4t_initrd_fails(tmp_path):
    rootfs = tmp_path / "rootfs"
    (rootfs / "boot").mkdir(parents=True)

    with pytest.raises(BuildError, match="nvidia-l4t-initrd"):
        _builder(tmp_path)._post_customize(rootfs, _config())


def test_fstab_mounts_only_rootfs():
    assert Tegra186RootfsBuilder.FSTAB_MOUNTS == (("LABEL=rootfs", "/", "ext4"),)


def test_factory_builds_rootfs():
    assert isinstance(tegra.create_builder("rootfs", None, None), Tegra186RootfsBuilder)
