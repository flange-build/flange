"""通用分区转换器 — 生成 sgdisk 命令序列。"""

from builder.partition import PartitionTable


class GenericPartitionConverter:
    """将分区配置转换为 sgdisk 命令序列。"""

    def convert(self, partition_config: dict) -> list:
        """返回 sgdisk 命令参数列表。"""
        table = PartitionTable.from_config(partition_config)
        commands = []
        part_num = 1
        for entry in table.entries:
            if entry.type == "raw":
                continue
            if entry.size == "remaining":
                size_arg = "0"  # sgdisk: 0 表示填充剩余空间
            else:
                size_arg = entry.size
            commands.append(f"-n{part_num}::{'+' + size_arg if size_arg != '0' else ''}")
            commands.append(f"-c{part_num}:{entry.name}")
            part_num += 1
        return commands
