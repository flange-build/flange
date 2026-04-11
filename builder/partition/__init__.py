"""分区表中间格式定义。"""

from dataclasses import dataclass, field


@dataclass
class Partition:
    """单个分区定义。"""
    name: str
    size: str       # "0x2000" (sectors), "4M", "remaining"
    type: str       # "raw", "ext4", "fat32"
    offset: str = ""  # "0x40" (sectors), 可选

@dataclass
class PartitionTable:
    """分区表定义。"""
    format: str = "gpt"
    sector_size: int = 512
    entries: list = field(default_factory=list)

    @classmethod
    def from_config(cls, config: dict) -> 'PartitionTable':
        """从配置 dict 构建 PartitionTable。"""
        table = cls(
            format=config.get("format", "gpt"),
            sector_size=config.get("sector_size", 512),
        )
        for entry in config.get("entries", []):
            table.entries.append(Partition(
                name=entry["name"],
                size=entry["size"],
                type=entry["type"],
                offset=entry.get("offset", ""),
            ))
        return table
