"""FINAL_CONFIG 校验。

把"配置上的隐性约定"显式化，让早期错误（缺字段、布局不一致）在 lunch /
load_current_config 阶段就抛出，而不是等到 build/flash 失败时才暴露。

覆盖范围（按需扩展，不追求完备）：
- recovery 子配置启用时，partitions.entries 必须包含 recovery 分区。

Recovery 子配置 schema（顶层 ``config["recovery"]``，全部可选；缺省即关闭）:

    recovery:
      enabled: bool                       # 默认 False。开启后 recovery 组件
                                          # 进入构建图，分区表必须含 recovery
      packages: list[str]                 # recovery rootfs 内 apt 安装的包
                                          # （systemd / udev / parted 等）
      custom_packages: list[str]          # 装入 recovery rootfs 的 custom App
                                          # 名（构建系统会从 components/app/ 取）
      transport: str                      # 首版仅支持 "adb"（USB ADB）
      protected_partitions: list[str]     # 显式声明的受保护分区名集合；
                                          # type=="raw" 的分区无论是否在表内
                                          # 都默认受保护，由设备端 recoveryctl
                                          # 强制（这里只补充非 raw 的额外名单）

可执行校验：调用方在拿到 ``resolve_config`` 结果之后立刻 ``validate_config(cfg)``。
"""

from __future__ import annotations

from builder.partition.size import parse_size


class ConfigError(ValueError):
    """配置层面的硬错误：在构建/刷写之前就应阻断。"""


def _is_recovery_enabled(config: dict) -> bool:
    """读取 ``config["recovery"]["enabled"]``，缺省视为 False。"""
    recovery_cfg = config.get("recovery") or {}
    return bool(recovery_cfg.get("enabled", False))


def _find_partition(config: dict, name: str) -> dict | None:
    """在 ``config["partitions"]["entries"]`` 中按名查询单个分区。"""
    entries = (config.get("partitions") or {}).get("entries") or []
    for entry in entries:
        if entry.get("name") == name:
            return entry
    return None


def validate_recovery_partition(config: dict) -> None:
    """recovery 启用时，强制 partitions.entries 中存在合规的 recovery 分区。

    要求：name=="recovery" 且 type=="ext4"，offset/size 必须非空字符串。
    """
    if not _is_recovery_enabled(config):
        return

    entry = _find_partition(config, "recovery")
    if entry is None:
        raise ConfigError(
            "recovery.enabled=True 但 partitions.entries 中缺少 recovery 分区；"
            "请在 SoC 或 board 配置的 partitions.entries 中加入 "
            "{name: 'recovery', type: 'ext4', offset, size}。"
        )

    if entry.get("type") != "ext4":
        raise ConfigError(
            f"recovery 分区 type 必须为 ext4，当前: {entry.get('type')!r}"
        )

    for field in ("offset", "size"):
        value = entry.get(field)
        if not value:
            raise ConfigError(
                f"recovery 分区缺少 {field}；offset 与 size 都必须显式声明。"
            )


def validate_rootfs_auto_grow(config: dict) -> None:
    """校验 rootfs 首次启动扩容布局。

    只有显式声明 ``grow_on_first_boot`` 的 rootfs 分区会进入校验。
    """
    entries = (config.get("partitions") or {}).get("entries") or []
    for index, entry in enumerate(entries):
        if not entry.get("grow_on_first_boot"):
            continue

        if entry.get("name") != "rootfs":
            raise ConfigError("grow_on_first_boot 仅支持 rootfs 分区。")
        if entry.get("type") != "ext4":
            raise ConfigError("grow_on_first_boot 要求 rootfs 分区 type 为 ext4。")
        image_size = entry.get("image_size")
        if not image_size:
            raise ConfigError(
                "grow_on_first_boot=True 时 rootfs 分区必须声明 image_size。"
            )

        image = parse_size(image_size)
        size = entry.get("size")
        if size == "remaining":
            for later in entries[index + 1:]:
                if later.get("type") != "raw":
                    raise ConfigError(
                        "grow_on_first_boot=True 且 size=remaining 时，"
                        "rootfs 必须是最后一个非 raw 分区。"
                    )
            continue

        partition = parse_size(size)
        if image.bytes > partition.bytes:
            raise ConfigError(
                f"rootfs image_size ({image.bytes} bytes) 不得大于 "
                f"分区 size ({partition.bytes} bytes)。"
            )


def _is_amp_enabled(config: dict) -> bool:
    """读取 ``config["amp"]["enabled"]``，缺省视为 False。"""
    return bool((config.get("amp") or {}).get("enabled", False))


def validate_amp(config: dict) -> None:
    """amp 启用时，强制配置自洽：mode 合法、soc_project 存在、partitions.entries
    含非 raw 的 amp 分区，且 amp 分区排在 remaining rootfs 之前。

    amp 分区必须非 raw：U-Boot 的 AMP loader 按 GPT 分区名 part_get_info_by_name
    ("amp") 定位 FIT，而 raw 分区不进 GPT（image.py 跳过）→ 声明 raw 会让 U-Boot
    永远 -ENODEV、从核不被拉起。
    """
    if not _is_amp_enabled(config):
        return

    amp = config.get("amp") or {}
    mode = amp.get("mode")
    if mode not in ("hal", "rt-thread"):
        raise ConfigError(
            f"amp.enabled=True 但 amp.mode 非法: {mode!r}（须为 'hal' 或 'rt-thread'）。"
        )
    if not amp.get("soc_project"):
        raise ConfigError(
            "amp.enabled=True 但缺少 amp.soc_project（如 rk3566 应设为 'rk3568'）。"
        )

    entry = _find_partition(config, "amp")
    if entry is None:
        raise ConfigError(
            "amp.enabled=True 但 partitions.entries 中缺少 amp 分区；请加入 "
            "{name: 'amp', type: 'ext4', offset, size}（须排在 remaining rootfs 之前）。"
        )
    if entry.get("type") == "raw":
        raise ConfigError(
            "amp 分区 type 不得为 raw（U-Boot 按 GPT 分区名定位 FIT，raw 不进 GPT）；"
            "请用 ext4 占位（image 不会格式化它，dd 进的裸 FIT 块原样保留）。"
        )
    for field in ("offset", "size"):
        if not entry.get(field):
            raise ConfigError(f"amp 分区缺少 {field}；offset 与 size 都必须显式声明。")

    # amp 分区必须排在 remaining rootfs 之前（grow rootfs 之后不可有非 raw 分区，
    # 否则连 validate_rootfs_auto_grow 也会拒绝）。
    entries = (config.get("partitions") or {}).get("entries") or []
    amp_idx = next((i for i, e in enumerate(entries)
                    if e.get("name") == "amp"), None)
    rootfs_idx = next((i for i, e in enumerate(entries)
                       if e.get("name") == "rootfs"), None)
    if (amp_idx is not None and rootfs_idx is not None
            and amp_idx > rootfs_idx
            and entries[rootfs_idx].get("size") == "remaining"):
        raise ConfigError(
            "amp 分区必须排在 remaining rootfs 之前（grow rootfs 之后不可有非 raw 分区）。"
        )


def validate_config(config: dict) -> None:
    """对 FINAL_CONFIG 执行全部已知校验，第一项失败即抛 ConfigError。"""
    validate_recovery_partition(config)
    validate_rootfs_auto_grow(config)
    validate_amp(config)
