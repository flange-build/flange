"""分区大小解析工具。

配置中的分区大小存在两类表达：
  - `0x400000` / `4194304`：按 sector 数解释，沿用旧分区表语义
  - `1536M` / `2G`：按字节容量解释，用于 rootfs 初始镜像大小
"""

from __future__ import annotations

from dataclasses import dataclass


SECTOR_SIZE = 512
DEFAULT_REMAINING_BYTES = 4 * 1024 * 1024 * 1024


@dataclass(frozen=True)
class PartitionSize:
    """解析后的分区大小。"""

    bytes: int
    sectors: int

    @property
    def mb(self) -> int:
        """向下取整的 MiB 数。"""
        return self.bytes // (1024 * 1024)


def _from_bytes(value: int, raw: str) -> PartitionSize:
    if value <= 0:
        raise ValueError(f"分区大小必须大于 0: {raw}")
    if value % SECTOR_SIZE != 0:
        raise ValueError(f"分区大小必须按 512B 对齐: {raw}")
    return PartitionSize(bytes=value, sectors=value // SECTOR_SIZE)


def parse_size(value: str | int) -> PartitionSize:
    """解析分区大小。

    无后缀或 `0x` 开头的值按 sector 数解释；`B`/`M`/`G` 后缀按字节容量
    解释。`B` 主要用于校验错误路径，实际配置推荐使用 `M`/`G`。
    """
    raw = str(value).strip()
    if not raw:
        raise ValueError("分区大小不能为空")
    suffix = raw[-1].upper()
    number = raw[:-1]

    if suffix == "B":
        return _from_bytes(int(number, 0), raw)
    if suffix == "M":
        return _from_bytes(int(number, 0) * 1024 * 1024, raw)
    if suffix == "G":
        return _from_bytes(int(number, 0) * 1024 * 1024 * 1024, raw)
    if suffix.isalpha():
        raise ValueError(f"不支持的大小单位: {raw}")

    sectors = int(raw, 0)
    if sectors <= 0:
        raise ValueError(f"分区 sector 数必须大于 0: {raw}")
    return PartitionSize(bytes=sectors * SECTOR_SIZE, sectors=sectors)


def default_remaining_size() -> PartitionSize:
    """返回兼容旧逻辑的 remaining 默认构建大小。"""
    return _from_bytes(DEFAULT_REMAINING_BYTES, "remaining")


def resolve_image_size(entry: dict) -> PartitionSize:
    """解析构建产物使用的初始镜像大小。

    `image_size` 优先；未声明时，固定分区沿用 `size`，`remaining` 沿用旧的
    4GB 默认值以保持兼容。
    """
    image_size = entry.get("image_size")
    if image_size:
        return parse_size(image_size)
    if entry.get("size") == "remaining":
        return default_remaining_size()
    return parse_size(entry["size"])
