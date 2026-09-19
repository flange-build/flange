"""usbmoded —— USB 工作模式管理服务。

三层架构：

    L3  scene        场景 = 能力集合 + 参数 + role，控制命令驱动切换编排
    L2  capabilities 原子 USB 能力，统一接口 + 自带参数
    L1  gadget/udc/configfs   configfs 原语、UDC 生命周期、平台竞态处理

L1 不认识任何具体 USB function —— 所有 function 相关行为都经由
capability.Capability 接口调用。这条约束由 tasks 2.11 的自查保证。

本服务替换了原先的 usbdevice shell 脚本。脚本中积累的平台竞态知识已
逐条迁移，对照表见变更目录下的 race-checklist.md；修改 L1 之前请先读它。
"""

__version__ = "1.0.0"
