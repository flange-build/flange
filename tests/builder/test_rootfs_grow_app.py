"""flange-rootfs-grow App 测试。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from builder.app_spec import load_spec


APP_DIR = Path("components/app/flange-rootfs-grow")
SCRIPT = APP_DIR / "scripts" / "flange-rootfs-grow"


def _write_fake_command(bin_dir: Path, name: str, body: str):
    path = bin_dir / name
    path.write_text(f"#!/bin/bash\nset -euo pipefail\n{body}\n")
    path.chmod(0o755)


def _fake_env(
    tmp_path: Path,
    *,
    growpart_nochange: bool = False,
    fail_growpart: bool = False,
) -> dict:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "commands.log"

    _write_fake_command(
        bin_dir,
        "lsblk",
        f"echo \"lsblk $*\" >> {log}\necho \"mmcblk0 5\"",
    )
    _write_fake_command(
        bin_dir,
        "sgdisk",
        f"echo \"sgdisk $*\" >> {log}",
    )
    growpart_body = f"echo \"growpart $*\" >> {log}"
    if growpart_nochange:
        growpart_body += "\necho \"NOCHANGE: partition 5 is size 123. it cannot be grown\" >&2"
        growpart_body += "\nexit 1"
    if fail_growpart:
        growpart_body += "\nexit 42"
    _write_fake_command(bin_dir, "growpart", growpart_body)
    _write_fake_command(
        bin_dir,
        "partx",
        f"echo \"partx $*\" >> {log}",
    )
    _write_fake_command(
        bin_dir,
        "resize2fs",
        f"echo \"resize2fs $*\" >> {log}",
    )

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["FLANGE_ROOTFS_GROW_ROOT_SOURCE"] = "/dev/mmcblk0p5"
    env["FLANGE_ROOTFS_GROW_MARKER"] = str(tmp_path / "rootfs-grown")
    env["FLANGE_ROOTFS_GROW_LOG"] = str(log)
    return env


def test_app_spec_declares_service_and_dependencies():
    spec = load_spec(APP_DIR)
    assert spec.app.name == "flange-rootfs-grow"
    assert spec.app.type == "service"
    assert spec.systemd is not None
    assert spec.systemd.unit == "systemd/flange-rootfs-grow.service"
    assert spec.systemd.auto_start is True
    assert "cloud-guest-utils" in spec.depends
    assert "gdisk" in spec.depends
    assert "e2fsprogs" in spec.depends
    assert "util-linux" in spec.depends


def test_script_expands_rootfs_and_writes_marker(tmp_path):
    env = _fake_env(tmp_path)

    result = subprocess.run([str(SCRIPT)], env=env, text=True)

    assert result.returncode == 0
    assert Path(env["FLANGE_ROOTFS_GROW_MARKER"]).exists()
    assert Path(env["FLANGE_ROOTFS_GROW_LOG"]).read_text().splitlines() == [
        "lsblk -no PKNAME,PARTN /dev/mmcblk0p5",
        "sgdisk -e /dev/mmcblk0",
        "growpart /dev/mmcblk0 5",
        "partx -u /dev/mmcblk0",
        "resize2fs /dev/mmcblk0p5",
    ]


def test_script_resizes_filesystem_when_partition_is_already_grown(tmp_path):
    env = _fake_env(tmp_path, growpart_nochange=True)

    result = subprocess.run([str(SCRIPT)], env=env, text=True)

    assert result.returncode == 0
    assert Path(env["FLANGE_ROOTFS_GROW_MARKER"]).exists()
    assert Path(env["FLANGE_ROOTFS_GROW_LOG"]).read_text().splitlines() == [
        "lsblk -no PKNAME,PARTN /dev/mmcblk0p5",
        "sgdisk -e /dev/mmcblk0",
        "growpart /dev/mmcblk0 5",
        "partx -u /dev/mmcblk0",
        "resize2fs /dev/mmcblk0p5",
    ]


def test_script_skips_when_marker_exists(tmp_path):
    env = _fake_env(tmp_path)
    Path(env["FLANGE_ROOTFS_GROW_MARKER"]).write_text("done\n")

    result = subprocess.run([str(SCRIPT)], env=env, text=True)

    assert result.returncode == 0
    assert not Path(env["FLANGE_ROOTFS_GROW_LOG"]).exists()


def test_script_failure_does_not_write_marker(tmp_path):
    env = _fake_env(tmp_path, fail_growpart=True)

    result = subprocess.run([str(SCRIPT)], env=env, text=True)

    assert result.returncode != 0
    assert not Path(env["FLANGE_ROOTFS_GROW_MARKER"]).exists()
