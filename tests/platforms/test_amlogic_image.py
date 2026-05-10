"""AmlogicImageBuilder 单元测试 — 验证 user area GPT 组装。

测试聚焦：
- PARTITION_IMAGES 仅含 boot / rootfs / recovery（**不含 bootloader**：
  Amlogic eMMC 启动靠 hw boot0，bootloader 不写在 raw.img 内 —— 这是
  与 rockchip 的关键差异）
- compile 写 GPT 表后按顺序 dd 各分区
- 缺失 partition 镜像（如 recovery 未生成）时跳过而非报错
- collect 返回 image 键
"""

from __future__ import annotations

from pathlib import Path

import pytest

from builder.platforms.amlogic.image import AmlogicImageBuilder


class FakeDocker:
    def __init__(self):
        self.commands: list[list[str]] = []

    def run(self, cmd: list[str], **kwargs):
        self.commands.append(list(cmd))


class FakeCache:
    def __init__(self, target_dir: Path):
        self.target_dir = target_dir


def _config():
    return {
        "platform": "amlogic",
        "soc": "s905d3",
        "board": "test-vim3l",
        "partitions": {
            "entries": [
                {"name": "boot",     "offset": "0x40",     "size": "0x20000",  "type": "ext4"},
                {"name": "recovery", "offset": "0x20040",  "size": "0x100000", "type": "ext4"},
                {"name": "rootfs",   "offset": "0x120040", "size": "0x100000",
                 "type": "ext4", "image_size": "0x100000"},
            ],
        },
    }


def _prepare_target(target_dir: Path, *, with_recovery: bool = True):
    """模拟前序组件产物：boot/boot.img + rootfs/rootfs.img (+ recovery)。"""
    (target_dir / "boot").mkdir(parents=True)
    (target_dir / "boot" / "boot.img").write_bytes(b"boot")
    (target_dir / "rootfs").mkdir(parents=True)
    (target_dir / "rootfs" / "rootfs.img").write_bytes(b"rootfs")
    if with_recovery:
        (target_dir / "recovery").mkdir(parents=True)
        (target_dir / "recovery" / "recovery.img").write_bytes(b"recovery")


def test_partition_images_excludes_bootloader():
    """关键差异点：raw.img 不含 bootloader。

    Rockchip 的 PARTITION_IMAGES 含 idbloader / uboot；Amlogic 不含 ——
    因为 Amlogic BootROM 走 hw boot0 而非 user area，bootloader 由 flash
    阶段单独写入 fastboot ``bootloader`` 目标。
    """
    keys = set(AmlogicImageBuilder.PARTITION_IMAGES.keys())
    assert keys == {"boot", "rootfs", "recovery"}
    assert "idbloader" not in keys
    assert "uboot" not in keys
    assert "bootloader" not in keys


def test_instantiate(tmp_path):
    builder = AmlogicImageBuilder(docker=FakeDocker(), source=None)
    assert builder.component == "image"
    assert builder.SECTOR_SIZE == 512


def test_compile_writes_gpt_and_dd_each_partition(tmp_path):
    """compile 先写 GPT，再 dd boot/recovery/rootfs 三分区。"""
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    _prepare_target(target_dir)

    docker = FakeDocker()
    builder = AmlogicImageBuilder(docker=docker, source=None)
    builder.cache = FakeCache(target_dir)
    builder.compile(None, _config())

    # 第 1 个 docker 命令是 truncate 创建空镜像
    assert docker.commands[0][0] == "truncate"
    # 紧接着是 parted mklabel gpt
    parted_label = [c for c in docker.commands
                    if c[:2] == ["parted", "-s"] and "mklabel" in c]
    assert parted_label, "缺少 parted mklabel gpt"
    # 三次 mkpart（boot / recovery / rootfs）
    mkparts = [c for c in docker.commands
               if "mkpart" in c]
    assert len(mkparts) == 3
    # 三次 dd
    dd_calls = [c for c in docker.commands if c[0] == "dd"]
    assert len(dd_calls) == 3


def test_compile_skips_recovery_when_missing(tmp_path):
    """recovery 镜像不存在时跳过 dd 而非报错。"""
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    _prepare_target(target_dir, with_recovery=False)

    docker = FakeDocker()
    builder = AmlogicImageBuilder(docker=docker, source=None)
    builder.cache = FakeCache(target_dir)
    builder.compile(None, _config())

    dd_calls = [c for c in docker.commands if c[0] == "dd"]
    # 只 dd boot 与 rootfs 两个分区
    assert len(dd_calls) == 2


def test_no_dd_targets_outside_user_area(tmp_path):
    """所有 dd 写入的偏移都 ≥ partitions.entries 起点（不写 user area
    起点之前的 boot0/uboot 区域）。"""
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    _prepare_target(target_dir)

    docker = FakeDocker()
    builder = AmlogicImageBuilder(docker=docker, source=None)
    builder.cache = FakeCache(target_dir)
    builder.compile(None, _config())

    dd_calls = [c for c in docker.commands if c[0] == "dd"]
    # 提取所有 seek=N 数值
    seeks = []
    for cmd in dd_calls:
        for arg in cmd:
            if arg.startswith("seek="):
                seeks.append(int(arg[len("seek="):]))
    # 最小 seek 是 boot 的 0x40 = 64 sectors（GPT 起点之后），不存在
    # 写入 sector 0x200 / 0x4000 等 boot0 / FIP 偏移的命令
    assert min(seeks) == 0x40


def test_collect_returns_image_key(tmp_path):
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    _prepare_target(target_dir)

    builder = AmlogicImageBuilder(docker=FakeDocker(), source=None)
    builder.cache = FakeCache(target_dir)
    builder.compile(None, _config())

    out = builder.collect(None, _config())
    assert "image" in out
    assert out["image"].name == "raw.img"
