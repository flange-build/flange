## Why

当前 USB gadget 由单个 shell 脚本 `components/app/adbd/scripts/usbdevice` 管理。它能工作，且沉淀了大量来之不易的平台竞态修复，但架构上有三个硬限制：

1. **配置在构建期固化，运行时无法切换。** function 组合只能来自 `/etc/usbdevice.conf`，想把调试口从 adb 切到 ums 必须改配置、重新构建、重新刷写。脚本里 `usb_load_config()` 预留过运行时入口（读 `/etc/.usb_config`），但 flange 从未创建该文件，它是一段从未执行过的死代码。
2. **没有分层，能力与编排混在一起。** 「有哪些 USB 能力」「当前该启用哪些」「怎么安全地切换」三件事全部铺在同一层 shell 里，无法单独组合、单独测试，也无法表达「场景」这一业务概念。
3. **device ↔ host 角色切换零支持。** 全脚本检索 `otg` / `dr_mode` / `usb_role`，仅在一条错误提示文本中出现。

同时脚本自身还有一处结构性问题：它用 `while [ -f TAG ]; do start-stop-daemon; sleep .5; done` 自制守护循环来保活 adbd / mtp-server，本质是在重新发明 systemd 的 `Restart=always`，而 ROCK 5B 上的 USB 雪崩（11 分钟堆积 360+ 循环、USB 每 2 秒断连）正是这个自制循环泄漏导致的。

## What Changes

以三层架构的 Python 服务**替换** `usbdevice` shell 脚本，脚本本体在本变更中移除：

- **L1 gadget 核心层**：configfs 原语、UDC 生命周期、枚举校验、全部平台竞态处理。不认识任何具体 function。
- **L2 原子能力层**：每个 USB function 是一个能力，实现统一接口（实例名、prepare、start、stop、状态、内核排序权重、互斥关系），并各自携带参数。覆盖 adb、ums、ncm/rndis、uvc、uac1/uac2，以及现有脚本已实现、不能回退的 mtp、hid、ntb。
- **L3 场景层**：场景 = 能力集合 + 各能力参数 + role。控制命令驱动场景切换，由本层编排 role 与 gadget 的先后顺序。
- **控制接口**：unix socket 上的 JSON-RPC 2.0（行分隔传输）+ `usb-mode` CLI，基于 `SO_PEERCRED` 分级授权。
- **daemon 生命周期交给 systemd**：每个带 daemon 的能力对应一个 unit，能力的 start/stop 即 `systemctl start/stop`。自制守护循环连同其整类 bug 一并消除。
- 新增 device ↔ host 角色切换的平台抽象层。

**BREAKING**：`usbdevice` 脚本及其 `/etc/usbdevice.conf` shell 配置格式被移除，替换为 L3 的场景定义文件。板级 overlay 中现有的 12 份 `usbdevice.conf` 需要迁移为新格式。

现有脚本中的 13 项平台竞态知识 SHALL 逐条对照迁移至 L1，并在新代码中保留原注释 —— 那些注释是这些硬件行为知识的唯一载体。

## Capabilities

### New Capabilities

- `usb-capability-layer`：原子能力层。定义单个 USB function 的统一接口契约、参数模型、内核排序权重、能力间互斥关系，以及各具体能力（adb / ums / ncm / uvc / uac / mtp / hid / ntb）的行为要求。
- `usb-role-switch`：device ↔ host 角色切换的平台抽象。平台探测顺序、各平台 sysfs 节点契约、切换原语与状态查询、不支持平台的显式报错行为。

### Modified Capabilities

- `usbdevice-gadget`：从「shell 脚本管理 USB gadget」改为「L1 gadget 核心层管理 USB gadget」。职责边界不变（configfs、UDC 生命周期、竞态处理），但实现载体、配置格式与 hook 扩展机制全部变更；脚本特有的契约被移除。
- `usb-mode-service`：本变更内早先定义为「薄层服务，复用 shell 脚本执行」，现改为「L3 场景层，直接驱动 L2 能力」。场景模型取代扁平的模式模型。
- `adbd-app`：adbd 的启动方式从脚本内自制守护循环改为 systemd unit 管理。

## Impact

- `components/app/adbd/scripts/usbdevice`：**移除**。其 13 项竞态知识迁移至 L1。
- `components/app/adbd/`：新增三层 Python 实现、控制接口、CLI、各能力的 systemd unit；`app.yaml` 大幅调整；`depends` 加入 `python3`（metapackage，非 `python3-minimal`）与 `python3-yaml`。
- `components/app/adbd/conf/usbdevice.conf` 及 **12 份板级 overlay 配置**：迁移为新的场景定义格式（YAML，与 flange 既有配置风格一致）。
- `components/app/adbd/udev/61-usbdevice.rules`：触发目标从 `systemctl reload usbdevice.service` 改为新服务的对应入口。
- `components/rootfs/config.jsonnet`：**不改动**。`usbmode` group 由服务启动时创建 —— 顶层 `groups` 会让所有用户默认入组，与分级授权的意图相悖。
- 受影响板子：全部 12 块已配置 USB gadget 的板子，均需重新验证 USB 基本功能。
- 风险集中：本变更采用一次性全量重写而非渐进迁移，13 项竞态知识需一次性全部迁移到位。

## 非目标

- 不做 USB 速度降级、VBUS/端口电源控制、多 gadget 多控制器实例。现有脚本取第一个 UDC 的行为在本次保持不变。
- 不在第一版交付 Type-C 的角色切换。Type-C 的 data role 变更需走 PD 的 DR_SWAP 协商，依赖 PD 控制器固件行为（Dragon Q8B 曾因 aDSP `charger_process` 崩溃导致插拔失联），本版先在普通 OTG 口验证机制。
- 不实现 UVC 的取流 daemon。现有脚本在 `uvc_start` / `uvc_stop` 处留有 TODO，本次迁移保持该缺口不变，不扩大范围。
- 不改变现有各 function 的对外行为。迁移以行为等价为准，不借机调整 USB 描述符、PID 映射规则或枚举表现。
- 不做图形界面，不监听 TCP。socket 仅监听本机 unix domain。
- 不保留新旧两套实现并行的开关。本变更为一次性替换，回退手段是回滚整个 App 的 deb 版本，而非运行时切换。
