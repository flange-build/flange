## Context

现有 USB gadget 栈由 `components/app/adbd/scripts/usbdevice` 单个 shell 脚本承载 —— 从 Rockchip Linux SDK 移植并在 ROCK 5B、Dragon Q6A、Dragon Q8B 上大幅加固过。它通过 configfs 管理 gadget，由 `usbdevice.service` 在 `sysinit.target` 与 `usb-gadget.target` 两条链路上拉起，并由 udev 规则在 `android_usb` / `udc` 状态变化时触发 reload。

这个脚本在结构上已经隐含了三层：`usb_*` 系列函数是 gadget 核心，`<func>_prepare/start/stop` 是各 function 的实现，`USB_FUNCS` 是退化成扁平列表的编排层。本次变更要做的是把这三层**显式化并重写为 Python**，而不是推倒重来 —— 新旧架构是同构的，这是本变更可行性的基础。

真正的难点不在架构，在**知识迁移**。脚本里有 13 处平台竞态处理，每一处都对应一个在真实硬件上花费大量时间定位的问题，而代码注释是这些硬件行为知识的唯一载体。任何一处遗漏都会让对应的坑重现，且由于采用一次性全量重写（见 D13），重现时难以二分定位到具体是哪一处。

## Goals / Non-Goals

**Goals:**

- 三层架构：gadget 核心 / 原子能力 / 场景，各层职责清晰、可单独测试。
- 运行时切换 USB 工作模式，无需重新构建或刷写。
- 运行时切换 device ↔ host 角色，并与 gadget 生命周期正确编排。
- 提供进程间控制接口与分级授权。
- 平台无关：机制全线通用，平台差异收敛到可探测的抽象层与板级配置。
- **13 项平台竞态知识零遗漏地迁移到 L1。**
- 消除自制守护循环，daemon 生命周期交给 systemd。

**Non-Goals:**

- 不做 USB 速度降级、VBUS/端口电源控制、多 gadget 多控制器实例。
- 不做 Type-C 的 data role 切换。
- 不实现 UVC 取流 daemon（沿用现有 TODO 缺口）。
- 不借机改变任何 function 的对外行为。
- 不保留新旧实现并行的运行时开关。

## Decisions

### D1：三层架构，L1 不认识任何具体 function

```
L3  场景层 (Scene)        场景 = 能力集合 + 各能力参数 + role；控制命令驱动切换编排
 ↓
L2  原子能力层 (Capability) 每个 USB function 一个能力，统一接口 + 自带参数
 ↓
L1  Gadget 核心层          configfs 原语 · UDC 生命周期 · 枚举校验 · 全部竞态处理
```

控制接口（socket + CLI）挂在 L3；role 抽象层与 L1 平级，由 L3 编排。

**层间约束**：L1 MUST NOT 包含任何 function 名称的判断分支 —— 这是检验分层是否真正成立的硬指标。现有脚本中 L1 与 L2 的耦合点（如 `usb_prepare` 里对 `adb`/`ums` 的特殊处理）必须在迁移时解开。

**本决策推翻了本变更早先的方案。** 早先设计为「usbmoded 是薄层，通过写 override 文件 + `systemctl reload usbdevice.service` 复用 shell 脚本执行」，理由是保守地保全脚本内的平台修复。该方案已被否决：它无法表达原子能力的独立组合与启停，场景层只能退化为对扁平 `USB_FUNCS` 的间接操作，分层名存实亡。代价是竞态知识必须显式迁移而非隐式保全（见 D2）。

### D2：13 项竞态知识逐条对照迁移，代码内保留原注释

这是本变更的风险核心，因此把清单固化在设计文档里，作为实现与验收的双向依据：

| # | 现有位置 | 知识 | 丢失后果 | 迁移目标 |
|---|---|---|---|---|
| 1 | `usb_wait_udc` | 等 UDC controller 就绪再读 | deferred probe 竞态下取到空 UDC | L1 UDC 探测 |
| 2 | `usb_start` | UDC bind 后 readback 校验 | echo 成功但 kernel 写失败，静默跑在坏状态 | L1 UDC 绑定 |
| 3 | `usb_wait_state` | 枚举状态轮询 | 只确认 bind，确认不了枚举 | L1 枚举校验 |
| 4 | `usb_bounce_connection` | soft_connect 翻转 D+ 上拉，**不动 ConfigFS/FFS** | 动了触发 `functionfs_unbind`，adbd 的 ep fd 永久失效 | L1 枚举恢复 |
| 5 | `usb_start` | 枚举失败区分 `not attached`（无主机，正常）与其他 | 没插线被误判故障，无限重试 | L1 枚举校验 |
| 6 | `usb_write` | 幂等写（先读比较，相同则跳过） | 无谓的 sysfs 写触发重新枚举 | L1 configfs 原语 |
| 7 | `usb_prepare` | idProduct 仅在 UDC 未绑定时写 | 触发 soft-disconnect + udev reload = 无限重置环 | L1 描述符管理 |
| 8 | `usb_prepare` | disconnect recovery 只 kill daemon、不拆 ConfigFS | 同 #4，FFS 永久损坏 | L1 断连恢复 |
| 9 | `usb_prepare` | function 变化时先 stop 再 start | 往已 bind 的 gadget 上加 function | L3 切换编排 |
| 10 | `usb_start_daemon` | 守护循环 per-daemon 语义 + 回收 | **ROCK 5B 雪崩**：11 分钟堆积 360+ 循环，USB 每 2 秒断连 | **不迁移，改由 systemd 承担（D3）** |
| 11 | 脚本尾部 | `flock` 互斥 | udev 与手动触发并发 | L1 或服务层单例锁 |
| 12 | `usb_funcs_sort` | 内核要求的 function 排序 `rndis uac uvc adb ntb ums mtp acm` | 描述符顺序错乱 | L2 能力的排序权重 |
| 13 | `usb_start` | 启动幂等守卫（已绑定且 function 未变则跳过） | 每次 udev 事件都重配，soft-disconnect 环 | L1 或 L3 |

实现时每一项 SHALL 在新代码中保留或改写自原注释，说明该处理存在的原因与对应的硬件现象。注释不是可选的文档工作 —— 它是这些知识在下一次重构中存活的唯一方式。

### D3：daemon 生命周期交给 systemd，自制守护循环不迁移

第 10 项知识刻意不迁移，而是消灭其存在的前提。每个带 daemon 的能力（adb → adbd、mtp → mtp-server）对应一个 systemd unit，能力的 start/stop 即 `systemctl start/stop <unit>`。

**收益**：自制循环这一整类 bug（泄漏、多循环并发抢同一 FunctionFS ep0、TAG_FILE 与全局状态读写不对称）直接消失；白拿 journal 日志与 cgroup 隔离。

**风险与验证要求**：adbd 持有 FunctionFS 的 ep fd，systemd 的重启退避策略与 FFS 生命周期的配合行为未经验证。这是本变更中**唯一引入全新运行时行为**的决策（其余均为等价迁移），必须单独设计验证场景，不能与其他改动混在一起验收。

### D4：原子能力的统一接口

每个能力 SHALL 提供：

- `instances` —— configfs 实例名（如 `ffs.adb`、`uvc.gs0`、`mass_storage.0`）
- `kernel_order` —— 内核要求的排序权重（来源见知识 #12）
- `conflicts` —— 与哪些能力互斥
- `params` —— 该能力的参数模型
- `prepare()` —— 实例创建后、UDC bind 前的 configfs 配置
- `start()` —— UDC bind 后的启动动作
- `stop()` —— 清理
- `status()` —— 运行状态

**能力必须带参数**，这不是可选设计：uvc 需要分辨率与格式列表（yuyv / mjpeg / h264）、ums 需要 backing file 路径与大小与文件系统类型与挂载策略、hid 需要二进制 report descriptor。参数模型是 L2 接口的一等公民。

覆盖范围：`adb`、`ums`、`ncm`/`rndis`、`uvc`、`uac1`、`uac2`，以及现有脚本已实现、不迁移即构成功能回退的 `mtp`、`hid`、`ntb`。`acm` 与 `rndis` 在现有脚本中无专用 prepare、走 configfs 标准 function 的通用路径，迁移时保持该处理方式。

### D5：场景模型

场景 = 能力集合 + 各能力参数 + role。role 与能力集合是两个正交维度，场景可以只设其一。

场景定义格式为 YAML，与 flange 既有的配置风格（`app.yaml`）保持一致。

rootfs 的 base 包集合中不含 PyYAML，因此 App 的 `depends` 需加入 `python3-yaml`（Ubuntu 标准包，体积很小）。不把它加进 base 包集合 —— 单个 App 的需要不应污染全线 rootfs。

**注意区分载体**：配置文件用 YAML，控制协议仍为行分隔 JSON（见 D9）。前者面向人工编辑与板级维护，后者面向程序解析且需要 `socat` / `nc` 可手工调试，两者诉求不同，不强行统一。

### D6：落在现有 `adbd` App 内，不新建独立 App

flange 的 App 系统**没有 App 间依赖的先例**（所有 `depends` 均为 apt 包名），引入它属于额外未知风险；且本变更替换的正是该 App 的核心内容。

**已知问题（不在本次修复）**：`adbd` 这个 App 名在本变更后将彻底名不副实 —— 它承载的是完整的 USB gadget 子系统，adb 只是其中一个能力。合理做法是后续单独做一次纯重命名重构，而非在本次功能变更里顺带处理。

### D7：实现语言 Python 3

rootfs base 包集合已含 `python3`，不新增依赖；`recoveryctl` App 是完整先例（`type: exec` + `build.system: none` + 单文件入口 + `depends: [python3]`，并注明须用 metapackage 而非 `python3-minimal`）。

### D8：单 socket + `SO_PEERCRED` 分级授权

只开 `/run/usbmode.sock`（`0666`），daemon 从 peer credential 读取 uid/gid：查询类命令放行，变更类命令要求 `uid == 0` 或属于 `usbmode` group。

**备选方案否决**：开两个不同权限的 socket —— 客户端要按操作类型选择连哪个，协议表面积翻倍，且细化授权策略必须改协议。`SO_PEERCRED` 把授权集中在 daemon 内部，是 systemd / polkit 的标准做法。

### D9：控制协议为行分隔 JSON

每行一个 JSON 对象，请求含 `cmd`，响应含 `ok`。选它是因为 `socat` / `nc` 可直接手工调试，无需专用客户端。不设计二进制协议 —— 无性能诉求。

### D10：role 切换按 sysfs 节点探测

按序探测，命中即用：

1. `/sys/class/usb_role/<controller>-role-switch/role` —— mainline dwc3 标准接口，取值 `none` / `host` / `device`
2. `/sys/devices/platform/*/otg_mode` —— Rockchip BSP 私有接口
3. 全部未命中 —— **明确报错并列出已尝试路径，不静默失败**

Type-C 的 `/sys/class/typec/port*/data_role` 本版不纳入探测链。

不静默失败是刻意的：USB 问题定位成本极高，「命令返回成功但硬件没动」会让排查者在错误方向上浪费大量时间。

### D11：role 与 gadget 的切换顺序由 L3 编排

切到 host：先停 gadget（解绑 UDC、清理 ConfigFS 链接），再写 role 节点。
切回 device：先写 role 节点，再启动 gadget。

顺序颠倒会留下悬空绑定（UDC 已被 role 切换接管但 gadget 仍认为自己 bound）。L2 的 role 切换原语 MUST NOT 感知 gadget 状态，编排只属于 L3。

### D12：切换默认不持久化

临时切换重启后复位，为误操作留退路（见 R1）；持久化需显式选项，切换到会切断控制通道的场景时还需强制确认标志。

### D13：一次性全量重写，风险以 checklist 结构化控制

采用一次性全量替换而非按能力垂直切片。代价是无法二分定位遗漏项，因此风险控制完全依赖 D2 的 13 项 checklist：每项迁移对应一个独立的验证场景，验收时逐项过。

回退手段是回滚整个 App 的 deb 版本，不提供运行时新旧切换开关（见非目标）。

### D14：板级配置迁移

12 份板级 `usbdevice.conf` 需迁移为新的场景定义格式。迁移以**行为等价**为准：迁移后各板的默认 function 组合、VID/PID、产品名、序列号来源必须与迁移前完全一致，不借机调整。

板级 overlay 对 `usbdevice.conf` 曾是**整文件覆盖**（ROCK 5B 的板级 conf 末尾有明确警告：App 层新增的键必须在板级手动跟进，否则默默丢失）。新格式 SHALL 采用可合并的分层结构，消除这个陷阱 —— 这是本次重写顺带解决的既有设计缺陷。

## Risks / Trade-offs

**R1：切到 host 会切断 adb 通道，造成自锁。** 经 adb 下发切换命令，命令一生效下发通道本身就消失，只能靠串口或断电恢复。
→ 缓解：默认启用超时自动回滚（切换后启动计时器，未在窗口内收到确认则自动切回）；CLI 检测到自身经 adb 调用时显式警告；持久化切换到此类场景需强制标志。

**R2：13 项竞态知识遗漏，是本变更最大的风险。** 一次性全量重写意味着遗漏不会在实现时暴露，而是在某块板子的某个特定时序下才浮现，且无法通过二分定位到具体遗漏项。
→ 缓解：D2 的清单作为实现与验收的双向依据，每项对应独立验证场景；新代码保留原注释；验收要求逐项确认而非整体「USB 能用」。

**R3：12 块板子全部需要重新验证。** 本变更触及所有已配置 USB gadget 的板子，而手头能实测的板子有限。
→ 缓解：D14 要求板级配置迁移以行为等价为准，降低单板差异；无法实测的板子明确标注为「已迁移未验证」，不声称支持。

**R4：adbd 交给 systemd 管理是唯一引入全新运行时行为的改动。** adbd 持有 FunctionFS ep fd，systemd 重启退避与 FFS 生命周期的配合未经验证。
→ 缓解：单独设计验证场景，与等价迁移部分分开验收；若验证失败，回退为在 L2 内实现 daemon 管理（但须重新防范知识 #10 那类泄漏）。

**R5：role 切换的硬件差异极大，单板验证无法覆盖全线。** mainline dwc3、Rockchip BSP、各 SoC 的 OTG 实现行为都不同。
→ 缓解：探测逻辑与切换原语分离；探测不到时明确报错而非猜测；首版只在实际验证过的板子上声明支持。

**R6：Type-C 场景的 role 切换涉及 PD 协商，风险显著高于普通 OTG 口。** Dragon Q8B 上曾出现 aDSP `charger_process` 崩溃导致 Type-C 插拔后彻底失联。
→ 缓解：本版不纳入 Type-C 探测链。

**R7：`usbdevice.service` 处于开机关键路径，重写失败会导致设备完全失联。** 该服务在 `sysinit.target` 阶段启动，adb 是多数板子唯一的调试通道。
→ 缓解：验证必须优先在有串口可用的板子上进行；任何一块板子的首次验证都不得在无串口的条件下进行。

**R8：持久化了错误场景会导致设备开机即失联。**
→ 缓解：持久化文件路径固定且可通过串口或刷写清除；提供一键 reset；文档明确风险。

## Migration Plan

本变更为破坏性替换，无平滑迁移路径：

1. 实现三层架构与全部能力，`usbdevice` 脚本在同一变更中移除。
2. 12 份板级配置按 D14 的行为等价原则迁移。
3. 逐块板子验证：优先有串口的板子；每块板子按 D2 的 13 项 checklist 逐项确认，而非只确认「USB 能用」。
4. 回退：回滚整个 App 的 deb 版本。不提供运行时开关。

## Open Questions

- 超时自动回滚（R1）的默认窗口取多少？需实测一次完整 role 切换 + 重新枚举耗时后确定。
- 知识 #11（`flock` 互斥）迁移到 L1 还是服务层单例？取决于新服务是否仍需响应 udev 触发 —— 若 udev 改为直接通知常驻服务而非拉起新进程，进程级互斥的需求形态会变。
- 知识 #13（启动幂等守卫）的状态存放位置。现有实现依赖 `/tmp/.usbdevice` 文件，常驻服务下可改为内存态，但需考虑服务重启后的状态重建。
- 各板实际支持哪些能力组合，需逐板确认后才能填写板级场景定义；首版可只提供通用场景，板级按需补充。
