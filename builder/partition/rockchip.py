"""Rockchip parameter.txt 生成器。"""

from builder.partition import PartitionTable


class RockchipPartitionConverter:
    """将分区配置转换为 Rockchip parameter.txt 格式。"""

    def convert(self, partition_config: dict) -> str:
        """从配置 dict 生成 parameter.txt 内容。"""
        table = PartitionTable.from_config(partition_config)
        lines = [
            "FIRMWARE_VER:1.0",
            "MACHINE_MODEL:rockchip",
            "MACHINE_ID:007",
            "MANUFACTURER:flange",
            "MAGIC:0x5041524B",
            "ATAG:0x00200800",
            "MACHINE:rockchip",
            "CHECK_MASK:0x80",
            "PWR_HLD:0,0,A,0,1",
            f"TYPE: {table.format.upper()}",
            f"CMDLINE:mtdparts=rk29xxnand:{self._build_mtdparts(table)}",
        ]
        return "\n".join(lines) + "\n"

    def _build_mtdparts(self, table: PartitionTable) -> str:
        """构建 mtdparts 字符串。"""
        parts = []
        for entry in table.entries:
            # idbloader 写在固定 sector 64，不进 mtdparts
            if entry.name == "idbloader":
                continue
            if entry.size == "remaining":
                parts.append(f"-@{entry.offset}({entry.name}:grow)")
            else:
                parts.append(f"{entry.size}@{entry.offset}({entry.name})")
        return ",".join(parts)
