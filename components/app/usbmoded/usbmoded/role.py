"""device ↔ host 角色切换的平台抽象。

对应 usb-role-switch spec。

设计约束（spec「角色切换原语」）：本模块 MUST NOT 包含任何 gadget 启停
逻辑。role 与 gadget 的先后顺序由 L3 场景层编排 —— 切到 host 必须先停
gadget 再写 role，切回 device 必须先写 role 再启 gadget，顺序颠倒会留下
悬空绑定。把编排放进原语会让这个顺序无法被上层控制。

另一条硬约束：探测不到可用节点时明确报错，**绝不静默失败**。USB 问题的
定位成本极高，一个「命令返回成功但硬件没动」的实现会让排查者在错误的
方向上浪费大量时间。
"""

from __future__ import annotations

import glob
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from . import configfs

log = logging.getLogger(__name__)


class Role(str, Enum):
    """归一化后的 USB 角色。

    屏蔽各平台节点的原始取值差异：mainline 用 device，Rockchip BSP 用
    peripheral，对上层都呈现为 DEVICE。
    """

    HOST = "host"
    DEVICE = "device"
    NONE = "none"

    @classmethod
    def parse(cls, value: str) -> "Role":
        raw = (value or "").strip().lower()
        if raw in ("host",):
            return cls.HOST
        if raw in ("device", "peripheral", "gadget"):
            return cls.DEVICE
        # "otg" 表示由硬件按 ID pin 自动协商，当前实际角色不由本节点表达，
        # 因此归一化为 NONE 而不是猜测一个方向。
        return cls.NONE


class RoleError(Exception):
    """角色切换失败或平台不支持。"""


@dataclass(frozen=True)
class RoleBackend:
    """一个可用的角色切换后端。"""

    kind: str
    node: Path
    #: 归一化取值到该平台实际写入值的映射。
    write_map: dict[Role, str]

    def read(self) -> Role:
        return Role.parse(configfs.read_attr(self.node) or "")

    def write(self, role: Role) -> None:
        """写入角色并回读校验。

        回读校验的意义与 UDC 绑定相同（知识 #2）：写 sysfs 的返回值不一定
        反映内核端的失败。不校验就等于静默失败。
        """
        if role not in self.write_map:
            raise RoleError(f"后端 {self.kind} 不支持切换到 {role.value}")
        target = self.write_map[role]
        try:
            self.node.write_text(target)
        except OSError as exc:
            raise RoleError(f"写入角色失败：{self.node} = {target}: {exc}") from exc

        actual = self.read()
        if actual is not role:
            raise RoleError(
                f"角色回读校验失败：{self.node} 期望 {role.value} "
                f"实际 {actual.value}（原始写入值 {target}）"
            )


#: 探测表。按顺序尝试，命中即用。新增平台只需在此追加一项。
#:
#: Type-C 的 /sys/class/typec/port*/data_role 刻意不在表内 —— 它的角色
#: 变更需走 PD 的 DR_SWAP 协商，依赖 PD 控制器固件行为（Dragon Q8B 曾因
#: aDSP charger_process 崩溃导致 Type-C 插拔后彻底失联），本版不纳入。
PROBE_TABLE: tuple[tuple[str, str, dict[Role, str]], ...] = (
    (
        "usb_role_switch",
        "/sys/class/usb_role/*/role",
        {Role.HOST: "host", Role.DEVICE: "device", Role.NONE: "none"},
    ),
    (
        "rockchip_otg_mode",
        "/sys/devices/platform/*/otg_mode",
        {Role.HOST: "host", Role.DEVICE: "peripheral"},
    ),
)


def probe() -> RoleBackend | None:
    """探测当前平台可用的角色切换后端，不可用返回 None。"""
    for kind, pattern, write_map in PROBE_TABLE:
        for match in sorted(glob.glob(pattern)):
            node = Path(match)
            # 必须可写才算可用 —— 只读节点无法用于切换，当作未命中继续
            # 探测下一项，避免探测成功但切换必然失败。
            if node.exists() and _writable(node):
                log.info("角色切换后端：%s（%s）", kind, node)
                return RoleBackend(kind=kind, node=node, write_map=write_map)
    return None


def _writable(node: Path) -> bool:
    import os

    return os.access(node, os.W_OK)


def attempted_paths() -> list[str]:
    """探测过的节点模式，用于不支持时的诊断信息。"""
    return [pattern for _, pattern, _ in PROBE_TABLE]


def require_backend() -> RoleBackend:
    """取可用后端，不可用时明确报错。

    错误信息列出已尝试的路径，让使用者能直接判断是平台确实不支持，
    还是 DTS 把 dr_mode 固定死了 —— dwc3 只在 dr_mode = "otg" 时才注册
    role switch 接口，被固定为 host 或 peripheral 的板子（如 Dragon Q8B）
    运行时切换本就不可用。
    """
    backend = probe()
    if backend is not None:
        return backend

    # 区分两种"不可用"，它们的解法完全不同：
    #
    # 1. usb_role class 下有设备但没有 role 属性 —— role switch 已经注册，
    #    只是内核没把接口暴露给 userspace。`role` 属性受
    #    usb_role_switch_is_visible() 控制，仅当注册方设置了
    #    allow_userspace_control 才可见。mainline 的 dwc3 从 v5.9 起设置了
    #    它，但厂商 BSP 常常没跟进 —— ROCK 5B 的 Rockchip 6.1 内核即是如此
    #    （dr_mode=otg、fusb302 正常工作，接口却被藏着）。这种情况改一行
    #    内核就能开启，与"平台真的不支持"是两回事。
    # 2. 完全没有节点 —— 多半是 DTS 把 dr_mode 固定成了 host/peripheral。
    #
    # 不做这个区分，排查者会误以为硬件不支持而放弃。
    registered = sorted(glob.glob("/sys/class/usb_role/*"))
    if registered:
        names = "、".join(Path(p).name for p in registered)
        raise RoleError(
            f"本平台已注册 USB role switch（{names}）但未向 userspace 暴露 "
            f"role 属性：内核注册时未设置 allow_userspace_control，"
            f"sysfs 接口被 usb_role_switch_is_visible() 隐藏。"
            f"这不是硬件限制 —— 在 dwc3 的 role switch 注册处补上该字段即可开启"
        )

    raise RoleError(
        "本平台不支持 USB 角色切换：已尝试 "
        + "、".join(attempted_paths())
        + " 均未找到可写节点，且 /sys/class/usb_role/ 下没有任何设备。"
        "若为 dwc3 平台，检查 DTS 的 dr_mode 是否被固定为 host/peripheral"
        " —— 仅 otg 模式会注册 role switch 接口"
    )


def current() -> tuple[Role, str | None]:
    """查询当前角色，返回 (角色, 不支持时的原因)。

    平台不支持时返回明确的「不支持」状态而非伪造默认值 —— 上层据此
    向用户报告，而不是让用户误以为角色是 none。
    """
    backend = probe()
    if backend is None:
        try:
            require_backend()
        except RoleError as exc:
            return Role.NONE, str(exc)
        return Role.NONE, "本平台不支持角色切换"
    return backend.read(), None


def switch(role: Role) -> None:
    """切换 USB 角色。

    本函数只写节点并校验，不感知 gadget 状态 —— 见模块文档的设计约束。
    """
    backend = require_backend()
    if backend.read() is role:
        log.debug("角色已是 %s，跳过", role.value)
        return
    log.info("切换角色：%s -> %s（%s）", backend.read().value, role.value, backend.node)
    backend.write(role)
