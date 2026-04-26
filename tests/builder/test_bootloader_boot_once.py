"""Bootloader recovery 配置选择补丁静态校验。"""

from __future__ import annotations

from pathlib import Path

from builder.base import ComponentBuilder


ROOT = Path(__file__).resolve().parents[2]
PATCH = (
    ROOT / "components" / "platform" / "rockchip" / "patches"
    / "bootloader" / "0002-select-flange-recovery-extlinux-conf.patch"
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
    text = PATCH.read_text(encoding="utf-8")
    assert "flange_boot_once" in text
    assert "flange_extlinux_conf" in text
    assert "recovery.conf" in text
    assert "boot_mode == BOOT_MODE_RECOVERY" in text
    assert "flange_select_extlinux_conf(boot_mode)" in text
    assert "${prefix}extlinux/${flange_extlinux_conf}" in text


def test_bootloader_patch_is_counted_by_build_system():
    counter = BootloaderPatchCounter(docker=None, source=None)
    count = counter._count_patches({
        "platform": "rockchip",
        "board": "tspi-rk3566",
    })
    assert count >= 2
