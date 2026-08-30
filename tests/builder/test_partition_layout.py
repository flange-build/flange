"""PartitionLayout —— 分区表的单一事实源。

**为什么需要它**：`partitions.entries` 此前在 5 类消费方各自解析，用了 4 种
互不相同的算法，同名的 `_partition_size_mb` 在 4 个文件里各有一份且函数体已
漂移。分区表是"镜像怎么装配"与"设备怎么刷写"共同的契约 —— 两侧算出不同偏移，
结果是刷进去起不来，且要到真刷机那一刻才发现。

这组测试锁住三件事：解析规则本身、`image_size` 覆盖在所有消费方一致生效、
以及 4K 介质的换算只在一处发生。
"""

from __future__ import annotations

import json

import pytest

from builder.partition.layout import PartitionLayout, ResolvedPartition


ENTRIES = [
    {"name": "idbloader", "type": "raw", "offset": "0x40", "size": "0x2000"},
    {"name": "boot", "type": "ext4", "offset": "0x8000", "size": "0x20000"},
    {"name": "rootfs", "type": "ext4", "offset": "0x28000",
     "size": "remaining", "image_size": "2G"},
]


def _layout(entries=None, **partitions) -> PartitionLayout:
    return PartitionLayout.from_config(
        {"partitions": {"entries": entries if entries is not None else ENTRIES,
                        **partitions}})


# ---------------------------------------------------------------------------
# 解析规则
# ---------------------------------------------------------------------------

def test_偏移与大小统一按512字节扇区表达():
    layout = _layout()
    boot = layout.require("boot")
    assert boot.offset_sectors == 0x8000
    assert boot.size_sectors == 0x20000
    assert boot.offset_bytes == 0x8000 * 512
    assert boot.size_mb == 64


def test_image_size覆盖size():
    """此前只有一半消费方认 image_size，另一半按 size 算 —— 偏移当场对不上。"""
    assert _layout().require("rootfs").size_mb == 2048


def test_remaining无image_size时沿用4G兼容默认():
    entries = [{"name": "rootfs", "type": "ext4", "size": "remaining"}]
    assert _layout(entries).require("rootfs").size_mb == 4096


@pytest.mark.parametrize("size,expected_mb", [
    ("0x2000", 4),      # sector 数
    ("4M", 4),          # 字节容量
    ("1G", 1024),
])
def test_size同时支持扇区数与容量后缀(size: str, expected_mb: int):
    """三个 boot.py 用 int(entry["size"], 0) 解析 —— 遇到 "4M" 直接 ValueError。"""
    entries = [{"name": "x", "type": "ext4", "size": size}]
    assert _layout(entries).require("x").size_mb == expected_mb


def test_无offset的分区从0算起():
    entries = [{"name": "x", "type": "ext4", "size": "4M"}]
    assert _layout(entries).require("x").offset_sectors == 0


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------

def test_缺失分区报错而不是静默兜底():
    """静默兜底一个默认值，代价是镜像装到错误偏移，刷机那一刻才发现。"""
    with pytest.raises(KeyError) as exc:
        _layout().require("userdata")
    assert "boot" in str(exc.value), "报错要列出已定义的分区"


def test_get缺失时返回None():
    assert _layout().get("userdata") is None


def test_raw分区不进文件系统列表():
    """raw 是裸数据区，建成 GPT 分区会占分区号并给固件一个不存在的文件系统。"""
    names = [part.name for part in _layout().filesystems]
    assert names == ["boot", "rootfs"]
    assert _layout().require("idbloader").is_raw


def test_总扇区数覆盖到最末分区末端():
    layout = _layout()
    rootfs = layout.require("rootfs")
    assert layout.total_sectors == rootfs.offset_sectors + rootfs.size_sectors


def test_label缺省取分区名可被覆盖():
    entries = [{"name": "esp", "type": "fat32", "size": "4M", "label": "EFI"}]
    assert _layout(entries).require("esp").label == "EFI"
    assert _layout().require("boot").label == "boot"


# ---------------------------------------------------------------------------
# 4K 介质换算
# ---------------------------------------------------------------------------

def test_4K介质按比例重算():
    """不换算的话 4K 盘上 "3G" 会被当成 3G/512 个 4K 扇区 —— 整盘虚胖 8 倍。"""
    layout = _layout().for_sector_size(4096)
    assert layout.require("idbloader").offset_sectors == 8       # 0x40 ÷ 8
    assert layout.require("idbloader").size_sectors == 0x400     # 0x2000 ÷ 8
    assert layout.require("boot").offset_sectors == 0x1000


def test_512介质换算是恒等():
    original = _layout()
    same = original.for_sector_size(512)
    assert [(p.name, p.offset_sectors, p.size_sectors) for p in same] == \
           [(p.name, p.offset_sectors, p.size_sectors) for p in original]


def test_换算保留原始entry():
    """消费方仍可能要读 image_size 之外的字段（storage 类型、UBI 参数等）。"""
    assert _layout().for_sector_size(4096).require("rootfs").raw["size"] == "remaining"


def test_sector_size默认512可被配置覆盖():
    assert _layout().sector_size == 512
    assert _layout(sector_size=4096).sector_size == 4096


# ---------------------------------------------------------------------------
# 消费方一致性：这才是这次重构真正要守住的东西
# ---------------------------------------------------------------------------

def test_所有消费方对同一份配置算出同一个尺寸():
    """rootfs / image / boot / parameter.txt 四侧此前用四种算法。

    分区表是装配侧与刷写侧共同的契约，算出不同的数就是刷进去起不来。
    """
    from unittest.mock import MagicMock

    from builder.platforms.rockchip.boot import RockchipBootBuilder
    from builder.platforms.rockchip.image import RockchipImageBuilder
    from builder.platforms.rockchip.rootfs import RockchipRootfsBuilder

    config = {"partitions": {"entries": [
        # boot 分区用容量后缀声明，并且带 image_size —— 两个此前会被
        # boot.py 的 int(size, 0) 打回原形的写法
        {"name": "boot", "type": "ext4", "offset": "0x8000",
         "size": "128M", "image_size": "64M"},
    ]}}

    image = RockchipImageBuilder(MagicMock(), MagicMock())
    rootfs = RockchipRootfsBuilder(MagicMock(), MagicMock())
    boot = RockchipBootBuilder(MagicMock(), MagicMock())

    expected_mb = 64
    assert rootfs._partition_size_mb(config, "boot") == expected_mb
    assert image._layout(config).size_mb("boot") == expected_mb
    assert PartitionLayout.from_config(config).size_mb("boot") == expected_mb
    # boot.py 不再有自己的 _partition_size_mb
    assert not hasattr(boot, "_partition_size_mb")


def test_parameter_txt与GPT用同一份几何():
    """parameter.txt 是设备侧读到的分区表，与 raw.img 的 GPT 必须一致。"""
    from builder.partition.rockchip import generate_parameter_txt

    text = generate_parameter_txt(ENTRIES, machine="RK3576")
    rootfs = _layout().require("rootfs")
    assert f"{rootfs.size_sectors:#010x}@{rootfs.offset_sectors:#010x}(rootfs)" in text


def test_flash_config的几何与GPT一致(tmp_path):
    """装配侧与刷写侧必须读到同一份数字。

    此前 GPT 路径把 config 里的字符串原样抄进 flash-config.json：声明
    `size: "remaining"` + `image_size: "2G"` 时，raw.img 的 GPT 里是 2G 而
    flash-config 里写着 "remaining"；声明 `size: "4M"` 时刷写侧的
    `int(part.size, 0)` 直接 ValueError。两者都要到真刷机那一刻才发现。
    """
    from unittest.mock import MagicMock

    from builder.flash.generate import FlashConfigGenerator
    from builder.platforms.rockchip.image import RockchipImageBuilder

    config = {
        "platform": "rockchip", "board": "b", "product": "default",
        "variant": "release", "soc": "rk3576", "flash_tool": "upgrade_tool",
        "storage": {"type": "emmc", "size": "8G"},
        "partitions": {"format": "gpt", "entries": [
            {"name": "idbloader", "type": "raw", "offset": "0x40",
             "size": "0x1F00"},
            {"name": "boot", "type": "ext4", "offset": "0x8000", "size": "4M"},
            {"name": "rootfs", "type": "ext4", "offset": "0x28000",
             "size": "remaining", "image_size": "2G"},
        ]},
    }

    written = FlashConfigGenerator().generate(config, tmp_path)
    by_name = {p["name"]: p
               for p in json.loads(written.read_text())["partitions"]}

    image = RockchipImageBuilder(MagicMock(), MagicMock())
    for part in image._layout(config):
        recorded = by_name.get(part.name)
        if recorded is None:
            continue  # 无镜像的分区不进 flash-config
        assert int(recorded["offset"], 0) == part.offset_sectors, part.name
        assert int(recorded["size"], 0) == part.size_sectors, part.name


def test_flash_config的size总是可解析(tmp_path):
    """刷写侧对每个分区做 int(part.size, 0) —— 抄进去的 "4M" 会当场炸。"""
    from builder.flash.generate import FlashConfigGenerator

    config = {
        "platform": "rockchip", "board": "b", "product": "default",
        "variant": "release", "soc": "rk3576", "flash_tool": "upgrade_tool",
        "storage": {"type": "emmc", "size": "8G"},
        "partitions": {"format": "gpt", "entries": [
            {"name": "boot", "type": "ext4", "offset": "0x8000", "size": "4M"},
        ]},
    }
    written = FlashConfigGenerator().generate(config, tmp_path)
    for part in json.loads(written.read_text())["partitions"]:
        int(part["offset"], 0)
        int(part["size"], 0)
