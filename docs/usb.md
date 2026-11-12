# USB gadget 子系统（usbmoded）

## 概述

设备端的 USB gadget 管理服务，提供原子能力的组合与运行时工作模式切换。
三层架构：场景层（业务）→ 原子能力层（单个 USB function）→ gadget 核心层
（configfs 与竞态处理）。以 `usb-mode` CLI 与 unix socket 上的 JSON-RPC 2.0 对外。

Rust 静态程序提供模式管理与 CLI，设备端不需要 Python/PyYAML。
服务分为 `usbmoded`（模式管理）与 `adbd`（独立守护进程），由 init 系统负责保活。
已验证范围见下表；完整 CLI、场景配置与 JSON-RPC 接口见[组件参考](../components/app/usbmoded/README.md)。

## 关键设计要点

- **L1 不认识任何具体 function。** 所有 function 行为经 `Capability` 接口调用，
  核心层不按具体能力名称分支。
- **能力自带排序权重。** 内核对 function 排列有顺序要求，权重由各能力声明，
  核心层不再持有硬编码顺序表，新增能力无需改 L1。
- **daemon 交给 systemd 或 OpenRC。** 按当前 init 管理服务，避免重复保活循环。
- **配置按键合并。** 板级只声明差异键，App 层新增的键自动对各板生效。
  旧的整文件覆盖语义曾导致 7 个键在 12 份板级配置中各重复一遍。
- **状态以 configfs 为唯一真实来源。** 服务重启后从 configfs 反推已启用能力，
  不依赖可能陈旧的状态文件。
- **失败不静默。** UDC 绑定回读校验、role 切换回读校验、平台不支持时明确报错并
  列出已尝试路径 —— USB 问题定位成本极高，「返回成功但硬件没动」代价太大。

## 关键代码位置

| 层 | 文件 | 职责 |
|---|---|---|
| L3 | `src/scene.rs` | 场景模型、切换编排、自锁回滚、持久化 |
| L3 | `src/control.rs` | Unix socket、JSON-RPC 2.0、`SO_PEERCRED` 授权与信号事件循环 |
| L2 | `src/capabilities.rs` | 能力接口、排序、11 种能力的生命周期 |
| L1 | `src/gadget.rs` | 描述符、生命周期编排、幂等守卫、断连恢复 |
| L1 | `src/system.rs` | ConfigFS 原语、UDC 校验、角色切换、init 命令边界 |
| — | `src/config.rs` | YAML 分层加载与按键合并 |

表中路径均位于 `components/app/usbmoded/`。入口为 `src/bin/usbmoded.rs`（服务）、
`src/bin/usb-mode.rs`（CLI）；构建及验收命令见[组件参考](../components/app/usbmoded/README.md#构建与验收)。

## 数据流

开机：当前 init 的 usbmoded 服务 → 加载配置 → 从 configfs 重建状态 → 进入持久化场景
（无则板级默认场景）→ 启动控制 socket。

切换：`usb-mode set <scene>` → socket → 授权判定 → 解析能力与互斥检查 →
按 role 方向编排（切 host 先停 gadget 后写 role；切 device 反之）→
按内核顺序建实例 → prepare → 建链接 → 绑定 UDC → start → 枚举校验。

udev 事件：USB 状态变化 → `/usr/lib/usbmoded/notify` 选择 systemd 异步 reload 或 OpenRC reload → SIGHUP →
重新评估（UDC 掉了走断连恢复；能力未变则被幂等守卫短路；开机场景因 UDC 尚未
注册而失败时，UDC 注册后在此重试开机场景）。开机场景仍未完成时另有 5–30 秒退避重试，
覆盖 adbd endpoint 延迟就绪且不产生新 udev 事件的情况。

## 平台竞态知识（13 项）

以下约束覆盖真实硬件上的故障原因。自动化使用伪 configfs 验证编排，不能代替设备时序和插拔测试。

| # | 知识 | 丢失后果 | 自动化覆盖 |
|---|---|---|---|
| 1 | 读 UDC 前等 controller 就绪 | deferred probe 平台取到空 UDC | 否（需真实时序） |
| 2 | UDC 绑定后回读校验 | 写失败被吞，静默运行在未绑定状态 | 是 |
| 3 | 枚举状态轮询 | 只确认 bind，确认不了枚举 | 是 |
| 4 | soft_connect bounce **不动 ConfigFS/FFS** | 触发 `functionfs_unbind`，adbd 的 ep fd 永久失效 | 部分 |
| 5 | 区分「无主机连接」与真实故障 | 没插线被判故障，systemd 无限重启 | 是 |
| 6 | configfs 幂等写 | 无谓写入触发重新枚举 | 是 |
| 7 | idProduct 仅在 UDC 未绑定时写 | soft-disconnect + udev reload = 无限重置环 | 是 |
| 8 | 断连恢复只重启 daemon、不拆 ConfigFS | 同 #4 | 是 |
| 9 | 能力变化先停后启 | 往已绑定的 gadget 上追加 function | 是 |
| 10 | 守护循环 per-daemon 语义 | **ROCK 5B 雪崩**：11 分钟堆积 360+ 循环 | 由 init 管理 |
| 11 | 并发互斥 | udev 与手动触发并发 | 否（需并发场景） |
| 12 | 内核要求的 function 排序 | 描述符顺序错乱 | 是 |
| 13 | 启动幂等守卫 | 每次 udev 事件都重配，重置环 | 是 |

自动化覆盖在 `components/app/usbmoded/src/tests.rs` 及传输层测试中，通过 Docker 内的
`cargo test --locked` 验证伪 ConfigFS 编排和真实 Unix socket 行为。
标「否」或「部分」的项目依赖真实硬件时序，只能实板验证。

## 板级验证范围

| 板卡 / 系统 | 已确认的行为 | 边界 |
| --- | --- | --- |
| ROCK 5B（Python 版本） | 场景切换、权限、自锁回滚、开机路径，device↔host 切换 | 依赖 dwc3 用户态 role 控制补丁；各场景仍受内核 function 支持限制 |
| [Jetson TX2](boards/nvidia-jetson-tx2.md)（Python 版本） | usbmoded + adbd、重启 adbd 后重连 | Linux 4.9 无 usb_role，不能切换 host/device |
| [RUBIK Pi 3](boards/thundercomm-rubikpi3.md)（Python 版本） | 延迟 UDC 的开机恢复；厂商内核的 USB 重连 | mainline 与厂商产品的 role/连接器行为分别判断 |
| [Luckfox](boards/luckfox-pico-pro-max.md) | 2026-11-12，Alpine/OpenRC；高精度内核与 USB 提前启动下正常重启、跨运行级别保留、网络延迟 15 秒时提前上线、3 次软断连、5 次 reload 和权限通过；Rust 版本另已验证串口场景和 host 自动回滚 | NAND 页等待与启动耗时见板卡页；新内核的 rootfs 首次空间修复、真实插拔与外接 USB Host 外设未测 |
| [ATK-RK3506B](boards/atk-rk3506b.md) | USB0 gadget 自动加载/绑定，ADB 与 USB1 Host 共存 | 早期记录使用旧服务，长期切换压力未验收 |

VID、gadget group 和默认场景来自当前 App 基线与板级 `overlay/etc/usbmode/`，不另维护易漂移的静态副本。
首次切换保留串口或网络 SSH 等带外通道；切到不含 ADB 的持久场景会改变下次启动的远程访问方式。

role 切换不可用有两种性质完全不同的原因，服务会分别诊断：

- **DTS 把 `dr_mode` 固定成 host/peripheral** —— dwc3 根本不注册 role switch
  接口，无解。Dragon Q8B 属于此类（其 DTS patch 固定为 `peripheral`）。RUBIK Pi 3 的
  Type-C dwc3 在 7.0.2 上打印 `dr_mode forced to gadget`，`/sys/class/usb_role` 为空，现象相同。
- **内核注册了但没暴露给 userspace** —— `role` 属性受
  `usb_role_switch_is_visible()` 控制，需注册方设置 `allow_userspace_control`。
  ROCK 5B 属于此类：`dr_mode=otg`、fusb302 工作正常、节点存在，只是属性被
  隐藏。Rockchip BSP 6.1 的 dwc3 未设该字段（mainline 自 v5.9 已设）。
  `components/platform/rockchip/patches/kernel/0001-usb-dwc3-allow-userspace-role-control.patch`
  补上该字段后，ROCK 5B 已完成 device↔host 切换的完整实板验证。

**role 切换是异步的**（实测约 200ms）：写入后 dwc3 要重新配置 controller
模式，UDC 随之消失或出现。任何「写完立即回读」的校验都会误判失败。

## 易踩坑

- **ConfigFS 返回的链接可能是相对路径**：内核会规范化链接目标；复用时比较解析后的对象，
  按路径字面值比较会误报不一致，导致断连后无法重新绑定。
- **清空 configfs 属性必须写换行符**，0 字节写入不触发内核 store 回调，
  解绑 UDC、清空 ums lun 会**静默失效**。
- **停用时不要删除 function 实例**，只解除 configuration 里的链接。删实例会
  销毁底层对象而挂载点残留，daemon 打开 ep0 后写描述符得到 EINVAL。
- **udev 触发的重新评估不能走 `switch`**，否则会取消自锁回滚计时器 ——
  切换本身就会引起 USB 状态变化并触发 udev。
- **UDC 可能远晚于服务注册**：RUBIK Pi 3 的 dwc3 依赖 pmic_glink 连接器，约 10 秒
  才出现，开机等待超时。重新评估若在无当前场景时直接返回，开机场景永不重试，
  设备停在无 adb 状态；须在 UDC 注册后重试开机场景。
- **ROCK 5B 内核只支持 ffs / mass_storage / acm / uvc**，通用场景里的
  `media`（mtp）与 `net`（ncm）在该板不可用；系统也缺 `mkfs.vfat`。
- **拆包后在已装旧版的设备上增量升级会撞 dpkg overwrite 冲突**，需先
  `dpkg -r adbd`。rootfs 全新构建不受影响。

- systemd 下服务在早期 sysinit 阶段启动；OpenRC 在 `boot` 中完成本地挂载、`bootmisc` 与设备初始化后，
  于 `networking` 之前启动 usbmoded。adbd 成功启动后标记为 `hotplugged`，否则跨运行级别时
  会被 OpenRC 当作手工服务停止。初始化期间的 SIGHUP 必须延后到场景建立后处理，避免递归重入。
- **`-p` 持久化到不含 adb 的场景会让设备每次开机都无法远程访问**，需 `--force`
  才能执行，恢复只能靠串口或重新刷写。
- **不要把 `usbmode` 加进 rootfs 顶层 `groups`。** 该字段的第二职是「作为每个
  user 的默认入组集合」，加进去会让所有普通用户自动获得切换权限。该组由服务
  启动时创建，授予用户需显式 `usermod -aG`。
- **YAML 里的十六进制要加引号。** 裸写的 `0x2207` 会被 YAML 1.1 解析成整数。
- **uvc 帧目录按高度命名**，同高不同宽的分辨率（640x480 与 800x480）会落到同一
  目录，后者被静默跳过。这是从 shell 实现继承的行为。

## 延伸阅读

- [adbd](../components/app/adbd/README.md) —— App 打包与 adbd 二进制来源
- [usbmoded 组件](../components/app/usbmoded/README.md) —— 能力清单、场景格式、CLI 与协议
