"""目标配置摘要。

把 `resolve_config` 的求值结果整理成**分节的表**，供 `lunch` 的选择界面与
其他需要"这个目标到底是什么配置"的场景共用。

为什么不直接把 25 个顶层键倒出来：那等于把配置分层想替用户省掉的工作又还
给他。用户在选目标时真正要确认的是有限几件事 —— 内核走哪个源、分区怎么切、
rootfs 装什么、recovery 与 amp 开没开、用哪个刷写工具。所以这里是一张**经过
挑选**的表，字段缺失时显示"—"而不是报错：摘要用于浏览，不该因为某块板没声明
某个可选字段就打断。
"""

from __future__ import annotations

from typing import Any

#: 一节摘要：(标题, [(键, 值), ...])
Section = tuple[str, list[tuple[str, str]]]

_MISSING = "—"


def _get(config: dict, *path: str, default: Any = None) -> Any:
    """按路径取值，任一层缺失即返回 default。"""
    node: Any = config
    for key in path:
        if not isinstance(node, dict):
            return default
        node = node.get(key)
        if node is None:
            return default
    return node


def _text(value: Any) -> str:
    if value is None or value == "" or value == []:
        return _MISSING
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value)
    return str(value)


def _source_text(config: dict, name: str | None) -> str:
    """把 source 引用渲染成 `url @ref`，本地源渲染成路径。"""
    if not name:
        return _MISSING
    descriptor = _get(config, "sources", name, default={}) or {}
    local = descriptor.get("local_path")
    if local:
        return f"{name} → 本地 {local}"
    url = descriptor.get("url")
    if not url:
        return name
    ref = descriptor.get("commit") or descriptor.get("branch")
    ref_text = f" @{ref[:12]}" if ref else ""
    return f"{name} → {url}{ref_text}"


def _identity(config: dict) -> Section:
    return (
        "身份",
        [
            ("board", _text(config.get("board"))),
            ("platform", _text(config.get("platform"))),
            ("soc", _text(config.get("soc"))),
            ("vendor", _text(config.get("vendor"))),
            ("product", _text(config.get("product"))),
            ("variant", _text(config.get("variant"))),
        ],
    )


def _architecture(config: dict) -> Section:
    return (
        "架构",
        [
            ("userspace", _text(_get(config, "architecture", "userspace"))),
            ("kernel", _text(_get(config, "architecture", "kernel"))),
            ("bootloader", _text(_get(config, "architecture", "bootloader"))),
        ],
    )


def _kernel(config: dict) -> Section:
    directory = _get(config, "kernel", "device_tree", "directory")
    name = _get(config, "kernel", "device_tree", "name")
    device_tree = f"{directory}/{name}" if directory and name else _text(name)
    oot = _get(config, "kernel", "oot_modules", default=[]) or []
    return (
        "内核",
        [
            ("source", _source_text(config, _get(config, "kernel", "source", "name"))),
            ("device_tree", device_tree),
            ("defconfig", _text(_get(config, "kernel", "defconfig"))),
            ("oot_modules", f"{len(oot)} 个" if oot else _MISSING),
        ],
    )


def _bootloader(config: dict) -> Section:
    return (
        "Bootloader",
        [
            ("source", _source_text(config, _get(config, "bootloader", "source", "name"))),
            ("defconfig", _text(_get(config, "bootloader", "defconfig"))),
            ("flash_tool", _text(config.get("flash_tool"))),
        ],
    )


def _storage(config: dict) -> Section:
    kind = _get(config, "storage", "type")
    size = _get(config, "storage", "size")
    storage = " / ".join(part for part in (kind, size) if part) or _MISSING
    rows = [
        ("storage", storage),
        ("分区格式", _text(_get(config, "partitions", "format"))),
        ("sector_size", _text(_get(config, "partitions", "sector_size", default=512))),
    ]
    for entry in _get(config, "partitions", "entries", default=[]) or []:
        size = entry.get("image_size") or entry.get("size")
        rows.append(
            (
                f"  {entry.get('name', '?')}",
                f"{entry.get('type', '?')}  off={entry.get('offset', '-')}  size={size}",
            )
        )
    return ("存储与分区", rows)


def _rootfs(config: dict) -> Section:
    url = _get(config, "rootfs", "url") or ""
    packages = _get(config, "rootfs", "packages", default=[]) or []
    custom = _get(config, "rootfs", "custom_packages", default=[]) or []
    return (
        "Rootfs",
        [
            ("base", url.rsplit("/", 1)[-1] if url else _MISSING),
            ("image_format", _text(_get(config, "rootfs", "image_format", default="ext4"))),
            ("apt 包", f"{len(packages)} 个" if packages else _MISSING),
            ("custom 包", _text(custom)),
            ("hostname", _text(_get(config, "rootfs", "hostname") or config.get("board"))),
            ("默认用户", _text(_get(config, "rootfs", "default_user"))),
        ],
    )


def _features(config: dict) -> Section:
    return (
        "功能开关",
        [
            ("recovery", _text(_get(config, "recovery", "enabled", default=False))),
            ("amp", _text(_get(config, "amp", "enabled", default=False))),
            ("packages", _text(config.get("packages"))),
            ("可选 product", _text(config.get("products"))),
            ("可选 variant", _text(config.get("variants"))),
        ],
    )


_SECTIONS = (_identity, _architecture, _kernel, _bootloader, _storage, _rootfs, _features)


def summarize_config(config: dict) -> list[Section]:
    """把已求值的配置整理成分节摘要表。"""
    return [builder(config) for builder in _SECTIONS]
