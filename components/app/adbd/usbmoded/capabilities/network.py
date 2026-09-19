"""网络类能力：ncm 与 rndis。

两者都把设备暴露为 USB 网卡，同时启用会让主机侧看到两个冲突的网络
接口，因此互斥。

既有 shell 实现中 rndis 走 configfs 标准 function 的通用路径、没有专用
配置逻辑（脚本里只有一行 "Nothing special" 注释）。迁移保持这一处理
方式，不引入新的配置步骤 —— 见 usb-capability-layer spec「网络能力」。
"""

from __future__ import annotations

from ..capability import ORDER_RNDIS, BaseCapability


class NcmCapability(BaseCapability):
    """USB NCM 网络接口。较 rndis 更现代，Linux/macOS 原生支持更好。"""

    name = "ncm"
    instances = ("ncm.gs0",)
    kernel_order = ORDER_RNDIS
    conflicts = frozenset({"rndis"})


class RndisCapability(BaseCapability):
    """USB RNDIS 网络接口。Windows 兼容性更好。"""

    name = "rndis"
    instances = ("rndis.gs0",)
    kernel_order = ORDER_RNDIS
    conflicts = frozenset({"ncm"})
