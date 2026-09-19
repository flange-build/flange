"""L2 原子能力层：能力注册表与互斥检查。

每个能力实现 capability.Capability 接口。本模块只负责登记与查询，
不含任何单个能力的行为逻辑。
"""

from __future__ import annotations

from ..capability import Capability, CapabilityError
from . import adb, media, network, serial_hid, storage

#: 能力名到实现的注册表。新增能力只需在此登记，L1 无需任何修改。
REGISTRY: dict[str, Capability] = {}


def register(cap: Capability) -> None:
    if cap.name in REGISTRY:
        raise ValueError(f"能力重复注册：{cap.name}")
    REGISTRY[cap.name] = cap


for _cap in (
    adb.AdbCapability(),
    storage.UmsCapability(),
    storage.MtpCapability(),
    media.UvcCapability(),
    media.Uac1Capability(),
    media.Uac2Capability(),
    network.NcmCapability(),
    network.RndisCapability(),
    serial_hid.AcmCapability(),
    serial_hid.HidCapability(),
    serial_hid.NtbCapability(),
):
    register(_cap)


def get(name: str) -> Capability:
    """按名取能力，不存在时报出可用清单。"""
    try:
        return REGISTRY[name]
    except KeyError:
        raise CapabilityError(
            f"未知能力：{name}（可用：{', '.join(sorted(REGISTRY))}）"
        ) from None


def resolve(names: list[str]) -> list[Capability]:
    """把能力名列表解析为能力对象，并做互斥检查。

    互斥在解析阶段就拒绝，确保不对 USB 硬件做任何操作 —— 这是
    usb-capability-layer spec「能力互斥检查」的要求。
    """
    caps = [get(n) for n in names]
    check_conflicts(caps)
    return caps


def check_conflicts(caps: list[Capability]) -> None:
    """检查能力集合内是否存在互斥组合。

    互斥声明是单向写就够的（如 ncm 声明与 rndis 冲突），本函数做双向
    检查，避免因为只在一侧声明而漏判。
    """
    names = {c.name for c in caps}
    for cap in caps:
        clash = sorted(cap.conflicts & names)
        if clash:
            raise CapabilityError(
                f"能力冲突：{cap.name} 不能与 {', '.join(clash)} 同时启用"
            )


def available() -> list[str]:
    """已注册的能力名，按内核排序权重排列。"""
    return [c.name for c in sorted(REGISTRY.values(), key=lambda c: (c.kernel_order, c.name))]
