"""Rockchip parameter、SPI NAND/UBI 与 AMP 分区配置校验。"""

from __future__ import annotations

from pathlib import Path

from builder.config.validate import (
    ConfigError,
    _byte_size,
    _find_partition,
    _positive_int,
)
from builder.partition.rockchip import (
    RockchipParameterEntry,
    parse_parameter_file,
    validate_parameter_capacity,
)
from builder.partition.size import resolve_image_size
from builder.paths import PROJECT_ROOT


def _parameter_path(config: dict) -> Path:
    value = (config.get("partitions") or {}).get("parameter")
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(
            "partitions.format=mtd 时必须声明 partitions.parameter 路径")
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _mtd_entries(config: dict) -> list[RockchipParameterEntry]:
    path = _parameter_path(config)
    try:
        return parse_parameter_file(path)
    except (OSError, ValueError) as exc:
        raise ConfigError(f"MTD parameter 校验失败: {exc}") from exc


def _gpt_parameter_entries(config: dict) -> list[RockchipParameterEntry]:
    configured = (config.get("partitions") or {}).get("entries") or []
    if not configured:
        raise ConfigError("SPI NAND GPT target 缺少 partitions.entries")

    entries: list[RockchipParameterEntry] = []
    names: set[str] = set()
    previous_end = 0
    for index, item in enumerate(configured):
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise ConfigError(f"partitions.entries[{index}] 缺少 name")
        if name in names:
            raise ConfigError(f"partitions.entries 存在重复分区名: {name}")
        names.add(name)
        try:
            offset = int(item.get("offset", "0"), 0)
            size = resolve_image_size(item).sectors
        except (TypeError, ValueError) as exc:
            raise ConfigError(
                f"GPT 分区 {name} 的 offset/size 非法: {exc}") from exc
        if offset < previous_end:
            raise ConfigError(
                f"GPT 分区 {name} 与前一分区重叠: "
                f"offset=0x{offset:x}, previous_end=0x{previous_end:x}")
        entry = RockchipParameterEntry(name=name, offset=offset, size=size)
        entries.append(entry)
        previous_end = offset + size
    return entries


def validate_storage(config: dict) -> None:
    """校验 Rockchip MTD/parameter、SPI NAND 容量与 UBI 分区映射。"""
    partitions = config.get("partitions") or {}
    partition_format = partitions.get("format", "gpt")
    storage = config.get("storage") or {}
    rootfs = config.get("rootfs") or {}
    rootfs_format = rootfs.get("image_format", "ext4")

    if partition_format == "mtd" and rootfs_format != "ubi":
        raise ConfigError("Rockchip partitions.format=mtd 要求 rootfs.image_format=ubi")
    if rootfs_format == "ubi" and storage.get("type") != "spinand":
        raise ConfigError(
            "Rockchip rootfs.image_format=ubi 要求 storage.type='spinand'")

    is_nand_ubi = partition_format == "mtd" or (
        partition_format == "gpt"
        and storage.get("type") == "spinand"
        and rootfs_format == "ubi"
    )
    if not is_nand_ubi:
        return

    storage_size = _byte_size(storage.get("size"), "storage.size")
    entries = (
        _mtd_entries(config)
        if partition_format == "mtd"
        else _gpt_parameter_entries(config)
    )
    try:
        validate_parameter_capacity(entries, storage_size)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
    if partition_format == "gpt":
        capacity_sectors = storage_size // 512
        last_end = max(entry.end or entry.offset for entry in entries)
        # 块设备 raw.img 已不用于 SPI NAND，但仍保留 1 MiB 尾部，避免生成的
        # parameter 占满介质后与 Rockchip GPT/loader 保留区冲突。
        if last_end + 2048 > capacity_sectors:
            raise ConfigError(
                f"GPT 分区末端 0x{last_end:x} 加尾部 0x800 sectors "
                f"超出存储容量 0x{capacity_sectors:x} sectors")

    rootfs_entry = next(
        (entry for entry in entries if entry.name == "rootfs"), None)
    if rootfs_entry is None:
        raise ConfigError("MTD parameter 中缺少具名 rootfs 分区")

    ubi = rootfs.get("ubi") or {}
    if ubi.get("mtd_index") is None:
        raise ConfigError("Rockchip rootfs.ubi 缺少 mtd_index")
    peb = _positive_int(ubi["peb_size"], "rootfs.ubi.peb_size")
    reserved = _positive_int(
        ubi["reserved_pebs"], "rootfs.ubi.reserved_pebs", allow_zero=True)
    volume_size = _byte_size(ubi["volume_size"], "rootfs.ubi.volume_size")
    mtd_index = _positive_int(
        ubi["mtd_index"], "rootfs.ubi.mtd_index", allow_zero=True)
    if mtd_index >= len(entries) or entries[mtd_index].name != "rootfs":
        actual = entries[mtd_index].name if mtd_index < len(entries) else "越界"
        raise ConfigError(
            f"rootfs.ubi.mtd_index={mtd_index} 对应 {actual!r}，期望 'rootfs'")

    partition_bytes = rootfs_entry.size_bytes(storage_size)
    assert partition_bytes is not None
    usable_bytes = partition_bytes - reserved * peb
    if usable_bytes <= 0 or volume_size > usable_bytes:
        raise ConfigError(
            f"rootfs UBI volume ({volume_size} bytes) 加坏块余量 "
            f"({reserved} PEB) 超过 MTD 分区 ({partition_bytes} bytes)")


def validate_amp(config: dict) -> None:
    """校验 Rockchip AMP 的具名 parameter/GPT 分区与容量。"""
    amp = config.get("amp") or {}
    if not amp.get("enabled", False):
        return

    partition_format = (config.get("partitions") or {}).get("format", "gpt")
    if partition_format == "mtd":
        entries = _mtd_entries(config)
        amp_entry = next(
            (entry for entry in entries if entry.name == "amp"), None)
        rootfs_entry = next(
            (entry for entry in entries if entry.name == "rootfs"), None)
        if amp_entry is None:
            raise ConfigError(
                "amp.enabled=True 但 MTD parameter 中缺少具名 amp 分区")
        if rootfs_entry is None:
            raise ConfigError("MTD parameter 中缺少具名 rootfs 分区")
        max_image_size = amp.get("max_image_size")
        if max_image_size is None:
            raise ConfigError(
                "MTD AMP target 必须声明 amp.max_image_size 以执行容量门禁")
        max_image_bytes = _byte_size(
            max_image_size, "amp.max_image_size")
        storage_size = _byte_size(
            (config.get("storage") or {}).get("size"), "storage.size")
        amp_partition_bytes = amp_entry.size_bytes(storage_size)
        if (amp_partition_bytes is None
                or max_image_bytes > amp_partition_bytes):
            raise ConfigError(
                f"amp.max_image_size ({max_image_bytes} bytes) 超过 MTD amp "
                f"分区 ({amp_partition_bytes} bytes)")
        return

    entry = _find_partition(config, "amp")
    if entry is None:
        raise ConfigError(
            "amp.enabled=True 但 partitions.entries 中缺少 amp 分区；请加入 "
            "{name: 'amp', type: 'ext4', offset, size}（须排在 rootfs 之前）。")
    if entry.get("type") == "raw":
        raise ConfigError(
            "amp 分区 type 不得为 raw（U-Boot 按 GPT 分区名定位 FIT，raw 不进 GPT）；"
            "请用 ext4 占位（image 不会格式化它，裸 FIT 原样写入）。")
    for field in ("offset", "size"):
        if not entry.get(field):
            raise ConfigError(
                f"amp 分区缺少 {field}；offset 与 size 都必须显式声明。")

    max_image_size = amp.get("max_image_size")
    if max_image_size is not None:
        max_image_bytes = _byte_size(
            max_image_size, "amp.max_image_size")
        try:
            partition_bytes = resolve_image_size(entry).bytes
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"GPT amp 分区 size 非法: {exc}") from exc
        if max_image_bytes > partition_bytes:
            raise ConfigError(
                f"amp.max_image_size ({max_image_bytes} bytes) 超过 GPT amp "
                f"分区 ({partition_bytes} bytes)")

    entries = (config.get("partitions") or {}).get("entries") or []
    amp_index = next((
        index for index, item in enumerate(entries)
        if item.get("name") == "amp"
    ), None)
    rootfs_index = next((
        index for index, item in enumerate(entries)
        if item.get("name") == "rootfs"
    ), None)
    if (amp_index is not None and rootfs_index is not None
            and amp_index > rootfs_index):
        raise ConfigError("GPT amp 分区必须排在 rootfs 之前。")


def validate_config(config: dict) -> None:
    """Rockchip 平台完整扩展校验入口。"""
    validate_storage(config)
    validate_amp(config)
