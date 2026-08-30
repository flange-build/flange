"""Rockchip armhf chroot、UBIFS/UBI 打包与 ext4 回归测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from builder.config.apps import gather_custom_packages
from builder.docker import BuildError
from builder.platforms.rockchip import ARTIFACT_NAMES
from builder.platforms.rockchip.rootfs import RockchipRootfsBuilder


class FakeDocker:
    """记录 rootfs 命令，并模拟 du/mkfs.ubifs/ubinize 产物。"""

    def __init__(self, *, ubifs_size=4096, ubi_size=8192, used_bytes=1024):
        self.commands: list[list[str]] = []
        self.privileged_commands: list[list[str]] = []
        self.ubifs_size = ubifs_size
        self.ubi_size = ubi_size
        self.used_bytes = used_bytes

    def run(self, cmd: list[str], **kwargs):
        self.commands.append(list(cmd))
        if cmd[:2] == ["du", "-sb"]:
            return SimpleNamespace(stdout=f"{self.used_bytes}\t{cmd[-1]}\n")
        if cmd and cmd[0] == "mkfs.ubifs":
            output = Path(cmd[cmd.index("-o") + 1])
            output.write_bytes(b"U" * self.ubifs_size)
        if cmd and cmd[0] == "ubinize":
            output = Path(cmd[cmd.index("-o") + 1])
            output.write_bytes(b"B" * self.ubi_size)
        return SimpleNamespace(stdout="")

    def run_privileged(self, cmd: list[str], **kwargs):
        self.privileged_commands.append(list(cmd))
        return SimpleNamespace(stdout="")


class FakeSource:
    def __init__(self, tarball: Path):
        self.tarball = tarball

    def ensure_rootfs_tarball(self, config: dict) -> Path:
        return self.tarball


class FakeChroot:
    """最小 ChrootContext 替身。"""

    instances = []

    def __init__(self, rootfs_dir: Path, docker):
        self.commands = []
        self.binds = []
        self.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def bind_mount(self, source, target):
        self.binds.append((source, target))

    def run(self, cmd, **kwargs):
        self.commands.append(list(cmd))


def _parameter(tmp_path: Path) -> Path:
    path = tmp_path / "parameter.txt"
    path.write_text(
        "TYPE: MTD\n"
        "CMDLINE:mtdparts=rk29xxnand:"
        "0x1000@0x0(security),0x2000@0x1000(uboot),"
        "0x1000@0x3000(misc),0x10000@0x4000(boot),"
        "0x2000@0x14000(amp),-@0x16000(rootfs)\n"
    )
    return path


def _ubi_config(tmp_path: Path) -> dict:
    return {
        "architecture": {
            "userspace": "armhf", "kernel": "arm", "bootloader": "arm",
        },
        "storage": {"type": "spinand", "size": "512M"},
        "partitions": {
            "format": "mtd",
            "parameter": str(_parameter(tmp_path)),
        },
        "rootfs": {
            "image_format": "ubi",
            "custom_packages": [
                "adbd", "recoveryctl", "flange-rootfs-grow"],
            "ubi": {
                "min_io_size": 2048,
                "peb_size": 131072,
                "subpage_size": 2048,
                "vid_hdr_offset": 2048,
                "leb_size": 126976,
                "max_leb_count": 3500,
                "space_fixup": True,
                "volume_size": "400M",
                "reserved_pebs": 20,
                "mtd_index": 5,
            },
        },
        "recovery": {"enabled": False},
    }


@pytest.mark.parametrize(
    "arch,expected",
    [
        ("armhf", "qemu-arm-static"),
        ("aarch64", "qemu-aarch64-static"),
    ],
)
def test_rootfs_emulator_mapping(arch, expected):
    config = {"architecture": {
        "userspace": arch, "kernel": "arm64", "bootloader": "arm",
    }}
    assert RockchipRootfsBuilder._rootfs_emulator(config) == expected


@pytest.mark.parametrize(
    "arch,expected_source",
    [
        ("armhf", "/usr/bin/qemu-arm-static"),
        ("aarch64", "/usr/bin/qemu-aarch64-static"),
    ],
)
def test_phase1_injects_arch_specific_emulator(
    monkeypatch,
    tmp_path,
    arch,
    expected_source,
):
    monkeypatch.setattr(
        "builder.rootfs.ChrootContext", FakeChroot)
    rootfs_dir = tmp_path / "rootfs"
    (rootfs_dir / "usr/bin").mkdir(parents=True)
    docker = FakeDocker()
    builder = RockchipRootfsBuilder(
        docker=docker, source=FakeSource(tmp_path / "base.tar.gz"))

    builder._build_phase1(
        rootfs_dir,
        {
            "architecture": {
                "userspace": arch, "kernel": "arm64", "bootloader": "arm",
            },
            "rootfs": {"packages": []},
        },
    )

    copy = next(cmd for cmd in docker.privileged_commands if cmd[0] == "cp")
    assert copy[1] == expected_source


def test_ubi_fstab_has_no_ext4_root_or_boot_entries(tmp_path):
    rootfs = tmp_path / "rootfs"
    (rootfs / "etc").mkdir(parents=True)
    builder = RockchipRootfsBuilder(docker=None, source=None)

    builder._install_fstab(rootfs, {"rootfs": {"image_format": "ubi"}})

    text = (rootfs / "etc/fstab").read_text()
    assert "LABEL=rootfs" not in text
    assert "LABEL=boot" not in text
    assert "kernel bootargs" in text  # 说明为何没有挂载项


def test_systemd_api_mountpoints_are_created(tmp_path):
    rootfs = tmp_path / "rootfs"
    rootfs.mkdir()

    RockchipRootfsBuilder._ensure_api_mountpoints(rootfs)

    for relative in (
        "proc",
        "sys/fs/cgroup",
        "dev/pts",
        "dev/shm",
        "run/lock",
        "tmp",
    ):
        assert (rootfs / relative).is_dir()
    assert (rootfs / "tmp").stat().st_mode & 0o7777 == 0o1777


def test_ext4_fstab_default_remains_unchanged(tmp_path):
    rootfs = tmp_path / "rootfs"
    (rootfs / "etc").mkdir(parents=True)
    builder = RockchipRootfsBuilder(docker=None, source=None)

    builder._install_fstab(rootfs, {})

    text = (rootfs / "etc/fstab").read_text()
    assert "LABEL=rootfs" in text
    assert "LABEL=boot" in text
    assert (rootfs / "boot").is_dir()


def test_ext4_builder_commands_and_artifact_remain_unchanged(
    monkeypatch,
    tmp_path,
):
    docker = FakeDocker()
    builder = RockchipRootfsBuilder(docker=docker, source=None)
    builder._work_dir = tmp_path / "work"
    builder._work_dir.mkdir()
    monkeypatch.setattr(builder, "_ensure_rootfs_fits_image", lambda *args: None)
    config = {
        "partitions": {
            "entries": [
                {"name": "rootfs", "size": "512M", "type": "ext4"},
            ],
        },
    }

    builder._build_image(tmp_path, config)

    assert docker.commands[0] == [
        "truncate", "-s", "512M", str(builder._work_dir / "rootfs.img")]
    assert docker.commands[1][:7] == [
        "mke2fs", "-t", "ext4", "-L", "rootfs", "-F", "-q"]
    assert builder.collect(None, config) == {"rootfs": builder._output}


def test_ubi_build_uses_explicit_geometry_and_rootfs_volume(tmp_path):
    config = _ubi_config(tmp_path)
    docker = FakeDocker()
    builder = RockchipRootfsBuilder(docker=docker, source=None)
    builder._work_dir = tmp_path / "work"
    builder._work_dir.mkdir()
    rootfs_dir = tmp_path / "rootfs"
    rootfs_dir.mkdir()

    builder._build_ubi(rootfs_dir, config)

    mkfs = next(cmd for cmd in docker.commands if cmd[0] == "mkfs.ubifs")
    assert mkfs[mkfs.index("-m") + 1] == "2048"
    assert mkfs[mkfs.index("-e") + 1] == "126976"
    assert mkfs[mkfs.index("-c") + 1] == "3500"
    assert "-F" in mkfs
    ubinize = next(cmd for cmd in docker.commands if cmd[0] == "ubinize")
    assert ubinize[ubinize.index("-p") + 1] == "131072"
    assert ubinize[ubinize.index("-s") + 1] == "2048"
    assert ubinize[ubinize.index("-O") + 1] == "2048"
    cfg = (builder._work_dir / "ubinize.cfg").read_text()
    assert "vol_name=rootfs" in cfg
    assert "vol_size=419430400" in cfg
    assert builder._output.name == "rootfs.ubi"
    assert builder.collect(None, config) == {"ubi": builder._output}
    assert ARTIFACT_NAMES[("rootfs", "ubi")] == "rootfs.ubi"


def test_ubi_space_fixup_is_opt_in(tmp_path):
    config = _ubi_config(tmp_path)
    del config["rootfs"]["ubi"]["space_fixup"]
    docker = FakeDocker()
    builder = RockchipRootfsBuilder(docker=docker, source=None)
    builder._work_dir = tmp_path / "work"
    builder._work_dir.mkdir()

    builder._build_ubi(tmp_path, config)

    mkfs = next(cmd for cmd in docker.commands if cmd[0] == "mkfs.ubifs")
    assert "-F" not in mkfs


def test_gpt_spinand_physical_limit_uses_generated_partition_size():
    config = {
        "storage": {"type": "spinand", "size": "512M"},
        "partitions": {
            "format": "gpt",
            "entries": [
                {"name": "rootfs", "offset": "0x30800", "size": "414M",
                 "type": "ext4"},
            ],
        },
        "rootfs": {"ubi": {"reserved_pebs": 82}},
    }

    limit = RockchipRootfsBuilder._ubi_physical_limit(config, 131072)

    assert limit == 414 * 1024 * 1024 - 82 * 131072


def test_ubi_staging_overflow_fails_before_mkfs(tmp_path):
    config = _ubi_config(tmp_path)
    docker = FakeDocker(used_bytes=401 * 1024 * 1024)
    builder = RockchipRootfsBuilder(docker=docker, source=None)
    builder._work_dir = tmp_path / "work"
    builder._work_dir.mkdir()

    with pytest.raises(BuildError, match="staging"):
        builder._build_ubi(tmp_path, config)
    assert not any(cmd[0] == "mkfs.ubifs" for cmd in docker.commands)


def test_ubinize_output_overflow_is_never_truncated(tmp_path):
    config = _ubi_config(tmp_path)
    # rootfs MTD 可用容量约 465MiB；模拟 500MiB UBI 产物。
    docker = FakeDocker(ubi_size=500 * 1024 * 1024)
    builder = RockchipRootfsBuilder(docker=docker, source=None)
    builder._work_dir = tmp_path / "work"
    builder._work_dir.mkdir()

    with pytest.raises(BuildError, match="禁止截断"):
        builder._build_ubi(tmp_path, config)


def test_ubi_route_filters_ext4_grow_app(tmp_path):
    config = _ubi_config(tmp_path)

    packages = gather_custom_packages(config)

    assert packages == ["adbd", "recoveryctl"]


def test_dockerfile_keeps_all_required_arm32_ubi_tools():
    text = Path("docker/Dockerfile").read_text()

    for package in (
        "mtd-utils",
        "u-boot-tools",
        "qemu-user-static",
        "gcc-arm-linux-gnueabihf",
        "gcc-aarch64-linux-gnu",
    ):
        assert package in text
    for command in (
        "command -v mkfs.ubifs",
        "command -v ubinize",
        "command -v mkimage",
        "command -v qemu-arm-static",
        "command -v arm-linux-gnueabihf-gcc",
        "command -v arm-linux-gnueabi-gcc",
    ):
        assert command in text
