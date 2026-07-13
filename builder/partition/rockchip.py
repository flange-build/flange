"""Rockchip parameter.txt 生成与解析工具。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from builder.partition import PartitionTable


_MTDPART_RE = re.compile(
    r"(?P<size>-|0x[0-9a-fA-F]+|[0-9]+)"
    r"@(?P<offset>0x[0-9a-fA-F]+|[0-9]+)"
    r"\((?P<label>[^)]+)\)"
)


@dataclass(frozen=True)
class RockchipParameterEntry:
    """parameter ``mtdparts`` 中的一个具名分区（单位为 512B sector）。"""

    name: str
    offset: int
    size: int | None
    flags: tuple[str, ...] = ()

    @property
    def end(self) -> int | None:
        """返回末尾 sector（开区间）；remaining 分区返回 ``None``。"""
        if self.size is None:
            return None
        return self.offset + self.size

    def size_bytes(self, storage_size_bytes: int | None = None) -> int | None:
        """返回字节容量；remaining 可结合总存储容量求值。"""
        if self.size is not None:
            return self.size * 512
        if storage_size_bytes is None:
            return None
        return storage_size_bytes - self.offset * 512


def parse_parameter_text(content: str) -> list[RockchipParameterEntry]:
    """解析 Rockchip parameter 的 ``CMDLINE:mtdparts=`` 分区列表。

    解析器同时兼容 ``rk29xxnand:`` 与空 device prefix（``mtdparts=:``），
    并保留 ``:grow`` / ``:bootable`` 等 flags。布局必须具名、无重叠、按
    offset 递增；remaining 分区只能位于最后。
    """
    cmdline = next(
        (line.strip() for line in content.splitlines()
         if line.strip().startswith("CMDLINE:")),
        None,
    )
    if cmdline is None or "mtdparts=" not in cmdline:
        raise ValueError("parameter.txt 缺少 CMDLINE:mtdparts= 分区声明")

    value = cmdline.split("mtdparts=", 1)[1].strip()
    if ":" not in value:
        raise ValueError("parameter.txt 的 mtdparts 缺少 device 分隔符 ':'")
    partition_list = value.split(":", 1)[1]
    if not partition_list:
        raise ValueError("parameter.txt 的 mtdparts 分区列表为空")

    entries: list[RockchipParameterEntry] = []
    names: set[str] = set()
    previous_end = 0
    segments = [segment.strip() for segment in partition_list.split(",")]
    for index, segment in enumerate(segments):
        match = _MTDPART_RE.fullmatch(segment)
        if not match:
            raise ValueError(f"无法解析 parameter 分区段: {segment!r}")
        labels = tuple(part for part in match.group("label").split(":") if part)
        if not labels:
            raise ValueError(f"parameter 第 {index} 个分区缺少名称")
        name, *flags = labels
        if name in names:
            raise ValueError(f"parameter 存在重复分区名: {name}")
        names.add(name)
        offset = int(match.group("offset"), 0)
        size_text = match.group("size")
        size = None if size_text == "-" else int(size_text, 0)
        if offset < previous_end:
            raise ValueError(
                f"parameter 分区 {name} 与前一分区重叠: "
                f"offset=0x{offset:x}, previous_end=0x{previous_end:x}")
        if size is not None and size <= 0:
            raise ValueError(f"parameter 分区 {name} size 必须大于 0")
        if size is None and index != len(segments) - 1:
            raise ValueError(f"parameter remaining 分区 {name} 必须位于最后")
        entry = RockchipParameterEntry(
            name=name,
            offset=offset,
            size=size,
            flags=tuple(flags),
        )
        entries.append(entry)
        previous_end = entry.end if entry.end is not None else offset
    return entries


def parse_parameter_file(path: str | Path) -> list[RockchipParameterEntry]:
    """读取并解析 parameter.txt。"""
    parameter_path = Path(path)
    if not parameter_path.is_file():
        raise FileNotFoundError(f"parameter.txt 不存在: {parameter_path}")
    return parse_parameter_text(parameter_path.read_text(encoding="utf-8"))


def validate_parameter_capacity(
    entries: list[RockchipParameterEntry],
    storage_size_bytes: int,
) -> None:
    """校验所有 parameter 分区都位于目标存储容量内。"""
    capacity_sectors = storage_size_bytes // 512
    for entry in entries:
        if entry.offset >= capacity_sectors:
            raise ValueError(
                f"parameter 分区 {entry.name} 起点 0x{entry.offset:x} "
                f"超出存储容量 0x{capacity_sectors:x} sectors")
        if entry.end is not None and entry.end > capacity_sectors:
            raise ValueError(
                f"parameter 分区 {entry.name} 末端 0x{entry.end:x} "
                f"超出存储容量 0x{capacity_sectors:x} sectors")


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
