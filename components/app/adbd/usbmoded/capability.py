"""L1 与 L2 之间的能力接口契约。

本模块定义 gadget 核心层调用原子能力的统一接口。它同时被 L1（调用方）
与 L2（实现方）依赖，因此单独成模块，不放在 capabilities 包内 —— 避免
L1 反向依赖具体能力的实现。

关键约束：L1 MUST NOT 针对具体能力名称分支，只能通过本接口操作能力。
这是检验分层是否真正成立的硬指标。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

# 知识 #12：内核对 function 排列顺序的约束。
#
# 既有 shell 实现把顺序写成一张硬编码表（usb_funcs_sort 的参数
# "rndis uac uvc adb ntb ums mtp acm"），未列出的 function 排在末尾。
# 本实现把顺序下放给各能力自行声明，L1 只按权重排序 —— 这样新增能力
# 不需要修改核心层。下面的常量只是给各能力引用的标准刻度。
ORDER_RNDIS = 10
ORDER_UAC = 20
ORDER_UVC = 30
ORDER_ADB = 40
ORDER_NTB = 50
ORDER_UMS = 60
ORDER_MTP = 70
ORDER_ACM = 80
# 未在内核顺序表中出现的能力排在最后，对应既有实现中
# "usb_funcs_grep -vE" 那一段的语义。
ORDER_DEFAULT = 100


@dataclass
class CapabilityContext:
    """能力执行时可见的环境。

    能力通过本对象访问自己的 configfs 实例目录，不直接拼接路径 ——
    gadget group 名是板级可配的，能力不应知道它。
    """

    gadget_dir: Path
    """gadget 根目录，如 /sys/kernel/config/usb_gadget/rockchip。"""

    config_dir: Path
    """configuration 目录，如 <gadget_dir>/configs/b.1。"""

    functions_dir: Path
    """function 实例的父目录，如 <gadget_dir>/functions。"""

    params: dict[str, Any] = field(default_factory=dict)
    """本次启用时场景提供的参数，已与能力默认值合并。"""

    def instance_dir(self, instance: str) -> Path:
        """某个 function 实例的 configfs 目录。"""
        return self.functions_dir / instance

    def link_path(self, instance: str) -> Path:
        """某个 function 实例在 configuration 下的链接路径。"""
        return self.config_dir / f"f-{instance}"


@dataclass
class CapabilityStatus:
    """能力的运行状态。"""

    name: str
    active: bool
    detail: str = ""


class CapabilityError(Exception):
    """能力操作失败。"""


@runtime_checkable
class Capability(Protocol):
    """原子 USB 能力的统一接口。

    生命周期顺序由 L1 编排：

        create instances → prepare() → link → bind UDC → start()

    停用时反向：

        stop() → unlink → remove instances

    prepare() 在 UDC 绑定**之前**调用，因此可以安全地写 configfs 属性；
    start() 在绑定**之后**调用，用于拉起依赖 endpoint 就绪的 daemon。
    这个区分不是风格问题 —— 写 configfs 属性时若 UDC 已绑定会触发
    soft-disconnect 与重新枚举（见 race-checklist.md 知识 #6、#7）。
    """

    @property
    def name(self) -> str:
        """能力名，场景定义中引用的标识。"""
        ...

    @property
    def instances(self) -> tuple[str, ...]:
        """本能力需要的 configfs function 实例名。

        多数能力只有一个实例；uvc 等可能有多个。
        """
        ...

    @property
    def kernel_order(self) -> int:
        """内核要求的排序权重，越小越靠前。见知识 #12。"""
        ...

    @property
    def conflicts(self) -> frozenset[str]:
        """与本能力互斥的其他能力名。"""
        ...

    @property
    def default_params(self) -> dict[str, Any]:
        """本能力的默认参数。场景提供的参数会覆盖同名键。"""
        ...

    def prepare(self, ctx: CapabilityContext) -> None:
        """实例已创建、UDC 尚未绑定时的 configfs 配置。"""
        ...

    def start(self, ctx: CapabilityContext) -> None:
        """UDC 已绑定后的启动动作，如拉起 daemon。"""
        ...

    def stop(self, ctx: CapabilityContext) -> None:
        """停止与清理。必须可重入 —— 未启动时调用应为空操作。"""
        ...

    def status(self, ctx: CapabilityContext) -> CapabilityStatus:
        """查询当前运行状态。"""
        ...


class BaseCapability:
    """能力实现的公共基类，提供各属性的合理默认值。

    能力可以不继承本类 —— Capability 是 Protocol，鸭子类型即可。
    提供基类只是为了减少样板代码。
    """

    name: str = ""
    instances: tuple[str, ...] = ()
    kernel_order: int = ORDER_DEFAULT
    conflicts: frozenset[str] = frozenset()
    default_params: dict[str, Any] = {}

    def prepare(self, ctx: CapabilityContext) -> None:
        """默认无需额外 configfs 配置 —— 标准 function 走通用路径。

        acm、rndis 等在既有 shell 实现中就没有专用 prepare，迁移时保持
        这一处理方式（见 usb-capability-layer spec「网络能力」）。
        """

    def start(self, ctx: CapabilityContext) -> None:
        """默认无需启动动作。"""

    def stop(self, ctx: CapabilityContext) -> None:
        """默认无需清理。"""

    def status(self, ctx: CapabilityContext) -> CapabilityStatus:
        """默认以实例目录是否存在作为活跃判据。"""
        active = all(ctx.instance_dir(i).is_dir() for i in self.instances)
        return CapabilityStatus(name=self.name, active=active)


def sort_by_kernel_order(caps: list[Capability]) -> list[Capability]:
    """按内核要求的顺序排列能力。知识 #12。

    同权重的能力按名称排序，保证结果稳定 —— 不稳定的顺序会让 PID 查找键
    （按能力名排序拼接）与实例创建顺序在不同运行间漂移。
    """
    return sorted(caps, key=lambda c: (c.kernel_order, c.name))
