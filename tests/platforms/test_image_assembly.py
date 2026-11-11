"""各平台镜像装配的分区选择与上游产物消费约束。"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.builder.context import component_context

PLATFORMS = {
    "rockchip": "builder.platforms.rockchip.image:RockchipImageBuilder",
    "allwinnera733": (
        "builder.platforms.allwinnera733.image:AllwinnerA733ImageBuilder"),
    "amlogic": "builder.platforms.amlogic.image:AmlogicImageBuilder",
    "qualcommqcs6490": (
        "builder.platforms.qualcommqcs6490.image:Qcs6490ImageBuilder"),
    "qualcommqrb2210": (
        "builder.platforms.qualcommqrb2210.image:Qrb2210ImageBuilder"),
    "nvidiategra186": (
        "builder.platforms.nvidiategra186.image:Tegra186ImageBuilder"),
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
        "board": "test-board",
        "product": "default",
        "variant": "release",
        "platform": "test-platform",
        "soc": "test-soc",
        "architecture": {
            "userspace": "aarch64", "kernel": "arm64", "bootloader": "arm64",
        },
        "kernel": {"device_tree": {"directory": "", "name": "test"}},
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
    if platform == "nvidiategra186":
        # tegraflash 刷写包由 BSP 刷写目录、kernel-dtb 与 rootfs 组装，分区来自 NVIDIA 模板；
        # 布局与 manifest 内容另由 Tegra186 image / flash 测试校验。
        from tests.platforms.tegra186_fixtures import image_config, upstream

        upstream(target)
        tegra = image_config()
        config = {**(config or _config()), **{key: tegra[key] for key in (
            "platform", "soc", "kernel", "bootloader", "partitions")}}

    builder = _load(PLATFORMS[platform])(MagicMock(), MagicMock())
    cache = MagicMock()
    cache.target_dir = target
    builder.cache = cache
    builder.context = component_context(tmp_path, {"board": "test-board"}, target_dir=target)
    builder.output = None

    calls: list[str] = []

    def record(name):
        def call(command, **kwargs):
            rendered = " ".join(str(part) for part in command)
            rendered = rendered.replace(str(target), "<TARGET>")
            rendered = rendered.replace(str(tmp_path), "<WORK>")
            calls.append(f"{name}: {rendered}")
            if command and command[0] == "./mksparse":
                (Path(kwargs["cwd"]) / command[-1]).write_bytes(b"sparse")
            return MagicMock()
        return call

    builder.docker.run.side_effect = record("run")
    builder.docker.run_privileged.side_effect = record("priv")

    try:
        if platform == "qualcommqrb2210":
            # QDL 组装器直接消费完整输入树；协议内容另由 UNO Q flash 测试校验。
            def bundle(firmware, images, output):
                record("bundle")([firmware, *[
                    f"{name}={path}" for name, path in images.items()
                ], output])
                return output

            with patch("builder.platforms.qualcommqrb2210.image.build_bundle", bundle):
                builder.compile(None, config or _config())
                assert builder.collect(None, config or _config()) == {"bundle": builder._bundle}
        else:
            builder.compile(None, config or _config())
    finally:
        work = getattr(builder, "_work_dir", None)
        if work and Path(work).exists():
            import shutil

            shutil.rmtree(work, ignore_errors=True)
    return calls


@pytest.mark.parametrize("platform", ["rockchip", "allwinnera733", "amlogic", "qualcommqcs6490"])
def test_gpt_contains_only_filesystems_at_configured_byte_offsets(platform, tmp_path):
    """验证实际生成的 GPT 分区与几何；raw 区域不能占用 GPT 分区号。"""
    commands = _run_compile(platform, tmp_path)
    partitions = re.findall(r"mkpart (\S+) (\S+) (\d+)B (\d+)B", "\n".join(commands))
    expected = [entry for entry in PARTITION_ENTRIES if entry["type"] != "raw"]
    assert [item[0] for item in partitions] == [entry["name"] for entry in expected]
    for (name, filesystem, start, end), entry in zip(partitions, expected, strict=True):
        offset = int(entry["offset"], 0) * 512
        assert (filesystem, int(start), int(end)) == (
            entry["type"], offset, offset + int(entry["size"], 0) * 512 - 1,
        ), name


@pytest.mark.parametrize("platform", PLATFORMS)
def test_disabled_recovery_is_not_written_even_when_old_image_exists(platform, tmp_path):
    config = _config()
    config["recovery"]["enabled"] = False
    commands = _run_compile(platform, tmp_path, config)
    rootfs = {
        "qualcommqrb2210": "rootfs=<TARGET>/rootfs/rootfs.img",
        "nvidiategra186": "cp --sparse=always <TARGET>/rootfs/rootfs.img",
    }.get(platform, "if=<TARGET>/rootfs/rootfs.img")
    assert any(rootfs in command for command in commands)
    assert not any("<TARGET>/recovery/recovery.img" in command for command in commands)
