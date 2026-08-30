"""PartitionLayout — 分区表的单一事实源。

**为什么需要它**：`partitions.entries` 此前在 5 类消费方各自解析一遍，用了
4 种互不相同的算法：

  - `builder/image.py`：`resolve_image_size(entry).bytes`（正确）
  - `builder/platforms/{rockchip,amlogic,allwinnera733}/boot.py`：
    `int(entry["size"], 0)` —— 忽略 `image_size`，且遇到 `"4M"` / `"remaining"`
    直接 ValueError
  - `builder/platforms/qualcommqcs6490/boot.py`：`int(e["size"],0)*512//MiB`
    —— 同样的缺陷，另一种写法
  - `builder/flash.py`：`int(part.size, 0)` 外加一个 `remaining` 特判

同名的 `_partition_size_mb` 在 4 个文件里各有一份，函数体已经漂移。分区表是
"镜像怎么装配"和"设备怎么刷写"两侧共同的契约 —— 两侧算出不同的偏移，结果是
刷进去起不来，而且要到真刷机那一刻才发现。

这个模块把"config → 已解析的分区布局"收成一次转换：偏移与大小统一按 flange
约定的 **512 字节扇区**表达，`image_size` 覆盖在这里统一应用，目标介质扇区
（UFS 是 4096）的换算由 `for_sector_size` 一处完成。消费方拿到的是数字，不再
自己解析字符串。
"""

from __future__ import annotations

from dataclasses import dataclass

from builder.partition.size import SECTOR_SIZE, resolve_image_size


@dataclass(frozen=True)
class ResolvedPartition:
    """一个分区解析后的几何。

    `offset_sectors` / `size_sectors` 一律按 flange 约定的 512 字节扇区计，
    与目标介质的逻辑块大小无关 —— 后者的换算是 `for_sector_size` 的事。
    """

    name: str
    type: str
    label: str
    offset_sectors: int
    size_sectors: int
    #: 原始 entry，供需要 `image_size` 之外字段的消费方读取。
    raw: dict

    @property
    def offset_bytes(self) -> int:
        return self.offset_sectors * SECTOR_SIZE

    @property
    def size_bytes(self) -> int:
        return self.size_sectors * SECTOR_SIZE

    @property
    def size_mb(self) -> int:
        return self.size_bytes // (1024 * 1024)

    @property
    def end_sectors(self) -> int:
        """末端（不含）扇区号。"""
        return self.offset_sectors + self.size_sectors

    @property
    def is_raw(self) -> bool:
        """裸数据区：不是文件系统，不进 GPT 分区表，直接 dd。"""
        return self.type == "raw"


class PartitionLayout:
    """已解析的分区布局。"""

    def __init__(self, entries: list[ResolvedPartition],
                 sector_size: int = SECTOR_SIZE, table_format: str = "gpt"):
        self.entries = tuple(entries)
        #: 目标介质的逻辑块大小（UFS 是 4096）。
        self.sector_size = sector_size
        self.format = table_format

    @classmethod
    def from_config(cls, config: dict) -> "PartitionLayout":
        partitions = config.get("partitions") or {}
        entries = []
        for entry in partitions.get("entries") or []:
            raw_offset = entry.get("offset")
            entries.append(ResolvedPartition(
                name=entry["name"],
                type=entry.get("type", ""),
                label=entry.get("label", entry["name"]),
                offset_sectors=int(raw_offset, 0) if raw_offset else 0,
                # image_size 覆盖在这里统一应用：此前只有一半消费方认它，
                # 另一半按 size 算，两边的偏移当场对不上。
                size_sectors=resolve_image_size(entry).sectors,
                raw=dict(entry),
            ))
        return cls(
            entries,
            sector_size=int(partitions.get("sector_size", SECTOR_SIZE)),
            table_format=partitions.get("format", "gpt"),
        )

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def __iter__(self):
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def __bool__(self) -> bool:
        return bool(self.entries)

    def get(self, name: str) -> ResolvedPartition | None:
        for entry in self.entries:
            if entry.name == name:
                return entry
        return None

    def require(self, name: str) -> ResolvedPartition:
        """取分区，缺失即报错。

        缺失分区一律是配置错误 —— 静默兜底一个默认值，代价是镜像装到错误
        的偏移，要到刷机那一刻才发现。
        """
        entry = self.get(name)
        if entry is None:
            available = ", ".join(part.name for part in self.entries) or "（空）"
            raise KeyError(
                f"partitions.entries 中未定义分区 {name!r}；已定义: {available}")
        return entry

    def size_mb(self, name: str) -> int:
        """分区的构建镜像大小（MiB），已应用 `image_size` 覆盖。"""
        return self.require(name).size_mb

    @property
    def filesystems(self) -> tuple[ResolvedPartition, ...]:
        """进 GPT 分区表的那些分区（排除 raw 裸数据区）。"""
        return tuple(entry for entry in self.entries if not entry.is_raw)

    @property
    def total_sectors(self) -> int:
        """覆盖全部分区所需的 512B 扇区数（不含 GPT 尾部保留）。"""
        return max((entry.end_sectors for entry in self.entries), default=0)

    def for_sector_size(self, sector_size: int) -> "PartitionLayout":
        """换算到目标介质的逻辑块大小。

        config 以 512B 声明；目标扇区是 4096（UFS）时不换算，"3G" 会被当成
        3G/512 个 4K 扇区 —— 整盘虚胖 8 倍，固件找不到分区。
        """
        if sector_size == SECTOR_SIZE:
            return PartitionLayout(list(self.entries), sector_size, self.format)
        ratio = SECTOR_SIZE / sector_size
        scaled = [
            ResolvedPartition(
                name=entry.name, type=entry.type, label=entry.label,
                offset_sectors=int(entry.offset_sectors * ratio),
                size_sectors=int(entry.size_sectors * ratio),
                raw=entry.raw,
            )
            for entry in self.entries
        ]
        return PartitionLayout(scaled, sector_size, self.format)
