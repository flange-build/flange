"""四个平台 recovery 构造序列的 golden 快照。

与 `test_rootfs_sequence_golden.py` 同构。`RecoveryBuilder` 与 `RootfsBuilder`
有 13 个同名方法，逐方法对比后其中 10 个只差参数名与 status 文案 —— 把它并进
基类是 `docs/refactor-roadmap.md` 重构清单的 #5。

recovery 的回归代价与 rootfs 同级：它是刷坏系统之后唯一的救援通道，构造错了
要等到真正需要它的那天才发现。所以先固化现状，合并时逐条比对。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from builder.packaging.model import PackageArtifact
from tests.builder.context import component_context

GOLDEN_DIR = Path(__file__).parent / "golden"

PLATFORMS = {
    "rockchip": "builder.platforms.rockchip.recovery:RockchipRecoveryBuilder",
    "allwinnera733": (
        "builder.platforms.allwinnera733.recovery:AllwinnerA733RecoveryBuilder"),
    "amlogic": "builder.platforms.amlogic.recovery:AmlogicRecoveryBuilder",
    "qualcommqcs6490": (
        "builder.platforms.qualcommqcs6490.recovery:Qcs6490RecoveryBuilder"),
}


def _load(spec: str):
    import importlib

    module, name = spec.split(":")
    return getattr(importlib.import_module(module), name)


def _config(platform: str) -> dict:
    return {
        "board": "golden-board",
        "product": "default",
        "variant": "release",
        "platform": platform,
        "soc": "golden-soc",
        "architecture": {
            "userspace": "aarch64", "kernel": "arm64", "bootloader": "arm64",
        },
        "kernel": {"device_tree": {"directory": "", "name": "golden"}},
        "rootfs": {
            "url": "https://example.com/ubuntu-base.tar.gz",
            "sha256": "a" * 64,
            "packages": ["systemd", "udev"],
        },
        "recovery": {
            "enabled": True,
            "packages": ["adb", "e2fsprogs"],
            "custom_packages": ["recoveryctl"],
            "protected_partitions": ["uboot"],
            "transport": "adb",
        },
        "storage": {"type": "emmc", "size": "8G"},
        "partitions": {
            "format": "gpt",
            "entries": [
                {"name": "uboot", "type": "raw", "offset": "0x4000",
                 "size": "0x4000"},
                {"name": "boot", "type": "ext4", "offset": "0x8000",
                 "size": "0x20000"},
                {"name": "recovery", "type": "ext4", "offset": "0x28000",
                 "size": "0x20000"},
                {"name": "rootfs", "type": "ext4", "offset": "0x48000",
                 "size": "remaining", "image_size": "2G"},
            ],
        },
        "amp": {"enabled": False},
    }


def _run_compile(platform: str, tmp_path: Path) -> list[str]:
    tmp_path = tmp_path.resolve()
    project_root = tmp_path / "project"
    (project_root / "components/recovery/overlay").mkdir(parents=True)
    (project_root / "components/recovery/overlay/hosts").write_text("127.0.0.1\n")

    target = project_root / ".build/target/golden-board/default/release"
    (target / "app").mkdir(parents=True)
    (target / "app/recoveryctl_1.0_arm64.deb").write_bytes(b"deb")
    (target / "kernel/modules/lib/modules/6.1.0").mkdir(parents=True)

    docker = MagicMock()
    source = MagicMock()
    source.ensure_download.return_value = Path("<TARBALL>")

    builder = _load(PLATFORMS[platform])(docker, source)
    cache = MagicMock()
    cache.target_dir = target
    cache.compute_phase_hash.return_value = "deadbeef"
    builder.cache = cache
    builder.context = component_context(project_root, {"board": "golden-board"}, target_dir=target)
    builder.output = None
    builder.app_report = MagicMock()
    builder.app_report.validate.return_value = True
    builder.app_report.runtime_packages_for.return_value = tuple(
        PackageArtifact(path, "deb", "runtime") for path in (target / "app").glob("*.deb")
    )

    calls: list[str] = []

    def record(name):
        def call(command, **kwargs):
            rendered = " ".join(str(part) for part in command)
            rendered = rendered.replace(str(project_root), "<PROJECT>")
            rendered = rendered.replace(str(tmp_path), "<WORK>")
            rendered = re.sub(
                r"/[^ ]*flange-recovery-[A-Za-z0-9_]+", "<TMP>", rendered)
            rendered = re.sub(
                r"recovery-base-[0-9a-f]+", "recovery-base-<HASH>", rendered)
            rendered = re.sub(r"<PROJECT>/.build/work/[^ ]+/recovery/run-[^ /]+", "<TMP>", rendered)
            rendered = re.sub(r"base-[0-9a-f]+", "base-<HASH>", rendered)
            rendered = re.sub(r"(base-<HASH>\.tar\.zst)\.[^ /]+\.tmp", r"\1.<TEMP>.tmp", rendered)
            calls.append(f"{name}: {rendered}")
            result = MagicMock()
            # recovery 分区 64MB，容量门禁保留 20%/至少 128MB —— 给一个
            # 真实救援系统量级的占用，否则门禁必然报"装不下"。
            result.stdout = "24\t<dir>"
            if command and str(command[0]) == "tar" and "-cf" in command:
                Path(command[command.index("-cf") + 1]).write_bytes(b"snapshot")
            # tar 是 mock 的，但后续步骤要往解出来的树里写文件
            if command and str(command[0]) == "tar" and "-C" in command:
                dest = Path(str(command[command.index("-C") + 1]))
                for sub in ("etc", "usr/bin", "lib/modules"):
                    (dest / sub).mkdir(parents=True, exist_ok=True)
            return result
        return call

    docker.run.side_effect = record("run")
    docker.run_privileged.side_effect = record("priv")

    previous = os.getcwd()
    os.chdir(project_root)
    try:
        builder.compile(None, _config(platform))
    finally:
        os.chdir(previous)
        work = getattr(builder, "_work_dir", None)
        if work and Path(work).exists():
            import shutil

            shutil.rmtree(work, ignore_errors=True)
    return calls


@pytest.mark.parametrize("platform", sorted(PLATFORMS))
def test_recovery构造序列与golden一致(platform: str, tmp_path: Path, request):
    """把 recovery 并进 RootfsBuilder 后，命令序列必须逐条不变。"""
    GOLDEN_DIR.mkdir(exist_ok=True)
    golden = GOLDEN_DIR / f"recovery-{platform}.json"

    actual = _run_compile(platform, tmp_path)

    if request.config.getoption("--update-golden", default=False):
        golden.write_text(
            json.dumps(actual, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        pytest.skip(f"已更新 golden: {golden.name}")

    assert golden.is_file(), (
        f"缺少 golden：先跑 pytest {__file__} --update-golden 固化现状")

    assert actual == json.loads(golden.read_text()), (
        f"{platform} 的 recovery 构造序列变了。recovery 是刷坏之后唯一的救援"
        f"通道，构造错了要等到真需要它那天才发现 —— 确认是有意变更再更新 golden。")


def test_golden覆盖全部平台():
    import builder.platforms as platforms_pkg

    available = {
        entry.name
        for entry in Path(platforms_pkg.__file__).parent.iterdir()
        if entry.is_dir() and entry.name != "__pycache__"
        and (entry / "recovery.py").is_file()
    }
    assert available == set(PLATFORMS), (
        f"这些平台有 recovery.py 但没进 golden 覆盖: {available - set(PLATFORMS)}")
