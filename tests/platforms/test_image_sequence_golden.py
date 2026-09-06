"""四个平台 image 装配序列的 golden 快照。

与 `test_rootfs_sequence_golden.py` 同构，锁的是 `compile()` 发出的命令序列。
image 家族的 AST 归一化对比显示 761 行中 261 行（34%）冗余、7 组同名函数中
5 组已漂移，收敛它是 `docs/refactor-roadmap.md` 的 R2 后半段。

image 的回归代价与 rootfs 同级：分区表写错、镜像 dd 到错误偏移，结果都是
板子刷不进去或起不来。所以先固化现状，合并时逐条比对。
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.builder.context import component_context

GOLDEN_DIR = Path(__file__).parent / "golden"

PLATFORMS = {
    "rockchip": "builder.platforms.rockchip.image:RockchipImageBuilder",
    "allwinnera733": (
        "builder.platforms.allwinnera733.image:AllwinnerA733ImageBuilder"),
    "amlogic": "builder.platforms.amlogic.image:AmlogicImageBuilder",
    "qualcommqcs6490": (
        "builder.platforms.qualcommqcs6490.image:Qcs6490ImageBuilder"),
}

# 覆盖各平台会消费的全部分区名，让"分区名→产物路径"映射的差异可见。
PARTITION_ENTRIES = [
    {"name": "idbloader", "type": "raw", "offset": "0x40", "size": "0x1F00"},
    {"name": "uboot", "type": "raw", "offset": "0x4000", "size": "0x4000"},
    {"name": "boot0", "type": "raw", "offset": "0x100", "size": "0x700"},
    {"name": "boot0_ufs", "type": "raw", "offset": "0x810", "size": "0x700"},
    {"name": "boot_package", "type": "raw", "offset": "0x6000", "size": "0x4000"},
    {"name": "boot", "type": "ext4", "offset": "0x8000", "size": "0x20000"},
    {"name": "recovery", "type": "ext4", "offset": "0x28000", "size": "0x20000"},
    {"name": "rootfs", "type": "ext4", "offset": "0x48000", "size": "0x100000"},
]

# 各平台可能消费的上游产物，全部预置，让"跳过不存在的镜像"不掩盖映射差异。
UPSTREAM_ARTIFACTS = [
    "bootloader/idbloader.img",
    "bootloader/u-boot.itb",
    "bootloader/boot0_sdcard.bin",
    "bootloader/boot0_ufs.bin",
    "bootloader/boot_package.fex",
    "boot/boot.img",
    "recovery/recovery.img",
    "rootfs/rootfs.img",
]


def _load(spec: str):
    import importlib

    module, name = spec.split(":")
    return getattr(importlib.import_module(module), name)


def _config() -> dict:
    return {
        "board": "golden-board",
        "product": "default",
        "variant": "release",
        "platform": "golden",
        "soc": "golden-soc",
        "architecture": {
            "userspace": "aarch64", "kernel": "arm64", "bootloader": "arm64",
        },
        "kernel": {"device_tree": {"directory": "", "name": "golden"}},
        "rootfs": {"image_format": "ext4"},
        "storage": {"type": "emmc", "size": "8G"},
        "partitions": {"format": "gpt", "entries": PARTITION_ENTRIES},
        "recovery": {"enabled": True},
        "amp": {"enabled": False},
        "rkbin": {"mkimage_chip": "rk3568"},
    }


def _run_compile(platform: str, tmp_path: Path, config=None) -> list[str]:
    tmp_path = tmp_path.resolve()
    target = tmp_path / "target"
    for relative in UPSTREAM_ARTIFACTS:
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\0" * 4096)

    builder = _load(PLATFORMS[platform])(MagicMock(), MagicMock())
    cache = MagicMock()
    cache.target_dir = target
    builder.cache = cache
    builder.context = component_context(tmp_path, {"board": "golden-board"}, target_dir=target)
    builder.output = None

    calls: list[str] = []

    def record(name):
        def call(command, **kwargs):
            rendered = " ".join(str(part) for part in command)
            rendered = rendered.replace(str(target), "<TARGET>")
            rendered = rendered.replace(str(tmp_path), "<WORK>")
            rendered = re.sub(
                r"/[^ ]*flange-image-[A-Za-z0-9_]+", "<TMP>", rendered)
            rendered = re.sub(r"<WORK>/.build/work/[^ ]+/image/run-[^ /]+", "<TMP>", rendered)
            calls.append(f"{name}: {rendered}")
            return MagicMock()
        return call

    builder.docker.run.side_effect = record("run")
    builder.docker.run_privileged.side_effect = record("priv")

    try:
        builder.compile(None, config or _config())
    finally:
        work = getattr(builder, "_work_dir", None)
        if work and Path(work).exists():
            import shutil

            shutil.rmtree(work, ignore_errors=True)
    return calls


@pytest.mark.parametrize("platform", sorted(PLATFORMS))
def test_image装配序列与golden一致(platform: str, tmp_path: Path, request):
    """重构 image 装配后，各平台发出的命令序列必须逐条不变。"""
    GOLDEN_DIR.mkdir(exist_ok=True)
    golden = GOLDEN_DIR / f"image-{platform}.json"

    actual = _run_compile(platform, tmp_path)

    if request.config.getoption("--update-golden", default=False):
        golden.write_text(
            json.dumps(actual, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        pytest.skip(f"已更新 golden: {golden.name}")

    assert golden.is_file(), (
        f"缺少 golden：先跑 pytest {__file__} --update-golden 固化现状")

    assert actual == json.loads(golden.read_text()), (
        f"{platform} 的 image 装配序列变了。分区表写错或镜像 dd 到错误偏移，"
        f"结果都是板子刷不进去 —— 确认这是有意的行为变更再更新 golden。")


def test_golden覆盖全部平台():
    import builder.platforms as platforms_pkg

    available = {
        entry.name
        for entry in Path(platforms_pkg.__file__).parent.iterdir()
        if entry.is_dir() and entry.name != "__pycache__"
        and (entry / "image.py").is_file()
    }

    assert available == set(PLATFORMS), (
        f"这些平台有 image.py 但没进 golden 覆盖: {available - set(PLATFORMS)}")


def test_raw类型分区不进GPT分区表(tmp_path: Path):
    """`raw` 表示"这块区域不是文件系统，直接 dd 裸数据"。

    把它建成 GPT 分区会占用分区号、并给固件一个不存在的文件系统分区。
    四个平台里曾有一个漏了这个判断（它的板配置恰好没有 raw 分区，所以从未
    暴露），收敛编排时统一。
    """
    raw_names = {e["name"] for e in PARTITION_ENTRIES if e["type"] == "raw"}
    assert raw_names, "测试配置需要包含 raw 分区才能验证这条规则"

    for platform in PLATFORMS:
        calls = _run_compile(platform, tmp_path / platform)
        mkpart = [c for c in calls if "mkpart" in c]
        for name in raw_names:
            assert not any(f"mkpart {name} " in c for c in mkpart), (
                f"{platform} 把 raw 分区 {name} 建进了 GPT")


@pytest.mark.parametrize("platform", PLATFORMS)
def test_disabled_recovery_is_not_written_even_when_old_image_exists(platform, tmp_path):
    config = _config()
    config["recovery"]["enabled"] = False
    commands = _run_compile(platform, tmp_path, config)
    assert any("if=<TARGET>/rootfs/rootfs.img" in command for command in commands)
    assert not any("if=<TARGET>/recovery/recovery.img" in command for command in commands)
