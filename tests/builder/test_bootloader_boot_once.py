"""Bootloader recovery 配置选择补丁静态校验。"""

from __future__ import annotations

from pathlib import Path

from builder.base import ComponentBuilder
from builder.platforms.allwinnera733 import bootloader as a733_bootloader
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
            "toolchain_tarball": "arm.tar.xz",
            "toolchain_url": "https://example.invalid/arm.tar.xz",
            "riscv_tarball": "riscv.tar.gz",
            "riscv_url": "https://example.invalid/riscv.tar.gz",
        },
    })

    commands = [" ".join(cmd) for cmd in docker.commands]
    patch_idx = next(
        i for i, cmd in enumerate(commands)
        if "git apply" in cmd and "allwinnera733/patches/bootloader" in cmd
    )
    make_idx = next(i for i, cmd in enumerate(commands) if cmd.startswith("make "))
    assert patch_idx < make_idx


def test_a733_toolchain_uses_cached_tarball_without_download(
    monkeypatch,
    tmp_path,
):
    cache_root = tmp_path / ".build"
    monkeypatch.setattr(a733_bootloader, "BUILD_ROOT", cache_root,
                        raising=False)
    cache_tarball = (
        cache_root / "cache" / "toolchains" / "allwinnera733"
        / "riscv.tar.gz"
    )
    cache_tarball.parent.mkdir(parents=True)
    cache_tarball.write_bytes(b"cached")
    dest_dir = tmp_path / "src" / "arisc" / "ar100s" / "tools"
    docker = RecordingDocker()
    builder = AllwinnerA733BootloaderBuilder(docker, source=None)

    builder._ensure_toolchain(
        label="RISC-V",
        tarball_name="riscv.tar.gz",
        tarball_url="https://example.invalid/riscv.tar.gz",
        dest_dir=dest_dir,
    )

    assert not any(cmd[0] == "wget" for cmd in docker.commands)
    assert [
        "tar", "xavf", str(cache_tarball), "-C", str(dest_dir),
    ] in docker.commands


def test_a733_toolchain_downloads_tarball_into_cache(monkeypatch, tmp_path):
    cache_root = tmp_path / ".build"
    monkeypatch.setattr(a733_bootloader, "BUILD_ROOT", cache_root,
                        raising=False)
    cache_tarball = (
        cache_root / "cache" / "toolchains" / "allwinnera733"
        / "riscv.tar.gz"
    )
    partial_tarball = cache_tarball.with_suffix(
        cache_tarball.suffix + ".download"
    )
    dest_dir = tmp_path / "src" / "arisc" / "ar100s" / "tools"
    docker = RecordingDocker()
    builder = AllwinnerA733BootloaderBuilder(docker, source=None)

    builder._ensure_toolchain(
        label="RISC-V",
        tarball_name="riscv.tar.gz",
        tarball_url="https://example.invalid/riscv.tar.gz",
        dest_dir=dest_dir,
    )

    assert [
        "wget", "-q", "-O", str(partial_tarball),
        "https://example.invalid/riscv.tar.gz",
    ] in docker.commands
    assert [
        "mv", str(partial_tarball), str(cache_tarball),
    ] in docker.commands
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
