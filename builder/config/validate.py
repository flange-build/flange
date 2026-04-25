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


def validate_config(config: dict) -> None:
    """对 FINAL_CONFIG 执行全部已知校验，第一项失败即抛 ConfigError。"""
    validate_recovery_partition(config)
