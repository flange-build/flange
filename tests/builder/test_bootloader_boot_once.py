"""Bootloader recovery 配置选择补丁静态校验。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from builder.base import ComponentBuilder
from builder.platforms.allwinnera733.bootloader import AllwinnerA733BootloaderBuilder


ROOT = Path(__file__).resolve().parents[2]
ROCKCHIP_PATCH = (
    ROOT / "components" / "platform" / "rockchip" / "patches"
    / "bootloader" / "0002-select-flange-recovery-extlinux-conf.patch"
)
A733_PATCH = (
    ROOT / "components" / "platform" / "allwinnera733" / "patches"
    / "bootloader" / "0001-select-flange-recovery-extlinux-conf.patch"
)


class BootloaderPatchCounter(ComponentBuilder):
    component = "bootloader"

    def configure(self, src_dir: Path, config: dict):
        pass

    def compile(self, src_dir: Path, config: dict):
        pass

    def collect(self, src_dir: Path, config: dict) -> dict:
        return {}


def test_recovery_conf_patch_contains_required_hooks():
    text = ROCKCHIP_PATCH.read_text(encoding="utf-8")
    assert "flange_boot_once" in text
    assert "flange_extlinux_conf" in text
    assert "recovery.conf" in text
    assert "boot_mode == BOOT_MODE_RECOVERY" in text
    assert "flange_select_extlinux_conf(boot_mode)" in text
    assert "${prefix}extlinux/${flange_extlinux_conf}" in text


def test_a733_recovery_conf_patch_contains_required_hooks():
    text = A733_PATCH.read_text(encoding="utf-8")
    assert "SUNXI_BOOT_RECOVERY_FLAG" in text
    assert "flange_boot_once" in text
    assert "flange_extlinux_conf" in text
    assert "recovery.conf" in text
    assert "flange_select_extlinux_conf(bootmode[0])" in text
    assert "env_save()" in text
    assert "${prefix}extlinux/${flange_extlinux_conf}" in text


def test_rockchip_bootloader_patch_is_counted_by_build_system():
    counter = BootloaderPatchCounter(docker=None, source=None)
    count = counter._count_patches({
        "platform": "rockchip",
        "board": "tspi-rk3566",
    })
    assert count >= 2


def test_a733_bootloader_patch_is_counted_by_build_system():
    counter = BootloaderPatchCounter(docker=None, source=None)
    count = counter._count_patches({
        "platform": "allwinnera733",
        "board": "radxa-cubie-a7z",
    })
    assert count >= 1


def test_a733_bootloader_build_applies_platform_patches(monkeypatch, tmp_path):
    src_dir = tmp_path / "u-boot-aw2501"
    src_dir.mkdir()
    docker = RecordingDocker()
    source = StaticSource(src_dir)
    builder = AllwinnerA733BootloaderBuilder(docker, source)
    monkeypatch.setattr(builder, "_reset_with_submodules", lambda src: None)
    monkeypatch.setattr(builder, "_ensure_toolchain", lambda **kwargs: None)
    monkeypatch.setattr(builder, "collect", lambda src, config: {})

    builder.build({
        "platform": "allwinnera733",
        "board": "radxa-cubie-a7z",
        "bootloader": {
            "target": "radxa-cubie-a7z",
            "toolchain": {
                "url": "https://example.invalid/arm.tar.xz",
                "sha256": "a" * 64,
            },
            "riscv_toolchain": {
                "url": "https://example.invalid/riscv.tar.gz",
                "sha256": "b" * 64,
            },
        },
    })

    commands = [" ".join(cmd) for cmd in docker.commands]
    patch_idx = next(
        i for i, cmd in enumerate(commands)
        if "git apply" in cmd and "allwinnera733/patches/bootloader" in cmd
    )
    make_idx = next(i for i, cmd in enumerate(commands) if cmd.startswith("make "))
    assert patch_idx < make_idx


def test_a733_toolchain_uses_verified_download(tmp_path):
    cache_tarball = tmp_path / "downloads" / "riscv.tar.gz"
    dest_dir = tmp_path / "src" / "arisc" / "ar100s" / "tools"
    docker = RecordingDocker()
    source = MagicMock()
    source.ensure_download.return_value = cache_tarball
    builder = AllwinnerA733BootloaderBuilder(docker, source=source)
    descriptor = {
        "url": "https://example.invalid/riscv.tar.gz",
        "sha256": "a" * 64,
    }

    builder._ensure_toolchain(
        label="RISC-V",
        descriptor=descriptor,
        dest_dir=dest_dir,
    )

    source.ensure_download.assert_called_once_with(
        "toolchains", "RISC-V", descriptor)
    assert [
        "tar", "xavf", str(cache_tarball), "-C", str(dest_dir),
    ] in docker.commands


class RecordingDocker:
    def __init__(self):
        self.commands = []

    def run(self, cmd, **kwargs):
        self.commands.append(cmd)


class StaticSource:
    def __init__(self, src_dir: Path):
        self.src_dir = src_dir

    def ensure(self, component: str, config: dict) -> Path:
        return self.src_dir
