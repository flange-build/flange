## MODIFIED Requirements

### Requirement: 平台无关的 USB gadget 管理

L1 gadget 核心层 SHALL 通过 Linux configfs 接口管理 USB gadget，自身不包含任何平台特定的硬编码值（VID、PID、产品名、厂商名等），也 MUST NOT 包含任何针对具体 USB function 名称的判断分支。

所有平台特定参数 SHALL 从板级配置加载。所有 function 特定行为 SHALL 由 L2 原子能力层提供。

后一条约束是检验分层是否真正成立的硬指标：现有 shell 实现中 L1 与 L2 的耦合点（如 gadget 准备阶段对 adb、ums 的特殊处理）必须在实现时解开。

#### Scenario: 核心层不含平台硬编码

- **WHEN** 检查 L1 实现
- **THEN** 其中不存在硬编码的 USB Vendor ID、Product ID、厂商名、产品名等平台特定值，这些值均从板级配置读取

#### Scenario: 核心层不含 function 名称分支

- **WHEN** 检查 L1 实现
- **THEN** 其中不存在对 `adb`、`ums`、`uvc` 等具体 function 名称的条件判断；L1 只按统一接口调用 L2 能力

### Requirement: 配置文件格式

板级 gadget 配置 SHALL 采用 YAML 格式，与 flange 既有的配置风格保持一致，支持以下配置项：

| 配置项 | 说明 | 示例值 |
|--------|------|--------|
| USB Vendor ID | USB 厂商标识 | `0x2207` |
| USB 产品名 | 宿主机显示的产品名 | `radxa-rock5b` |
| USB 厂商名 | 宿主机显示的厂商名 | `rockchip` |
| gadget group 名 | configfs gadget 目录名 | `rockchip` |
| 默认场景 | 开机进入的场景名 | `debug` |
| 序列号来源 | `cpuinfo` / `random` / 字面值 | `cpuinfo` |
| PID 映射表 | 各能力组合对应的 Product ID | 见「PID 动态映射」 |

配置 SHALL 采用可合并的分层结构：App 层提供通用默认值，板级 overlay 只声明需要覆盖的键，两者按键合并。

板级配置 MUST NOT 采用整文件覆盖语义。现有 shell 实现中板级 `usbdevice.conf` 整文件覆盖 App 层 conf，导致 App 层新增的键在各板默默丢失（ROCK 5B 板级配置末尾有此警告）；新格式必须消除这一陷阱。

#### Scenario: 板级只声明差异键

- **WHEN** App 层默认配置含 10 个键，板级配置只声明其中 3 个键的覆盖值
- **THEN** 最终生效配置为 10 个键，其中 3 个取板级值、7 个取 App 层值；App 层后续新增的键自动对该板生效

#### Scenario: 新增 App 层配置键不丢失

- **WHEN** App 层配置新增一个键，而板级配置未提及该键
- **THEN** 该键的 App 层值对所有板子生效，无需在 12 份板级配置中逐一跟进

### Requirement: PID 动态映射

L1 SHALL 根据当前启用的能力组合，从板级配置的 PID 映射表中查找对应的 Product ID。未找到匹配时使用默认 PID。

查找键的生成规则：将能力名按字母排序、用下划线连接。例如能力组合 `adb` + `mtp` 对应键 `adb_mtp`。

此规则与既有 shell 实现保持一致，以保证各板迁移后枚举到的 PID 不变。

#### Scenario: 单 adb 能力的 PID

- **WHEN** 启用能力为 `adb`，且板级配置中该键映射到 `0x0006`
- **THEN** gadget 的 idProduct 被设为 `0x0006`

#### Scenario: 未配置组合使用默认 PID

- **WHEN** 启用能力为 `adb` + `mtp`，板级配置中无 `adb_mtp` 键，默认 PID 为 `0x0019`
- **THEN** gadget 的 idProduct 被设为 `0x0019`

#### Scenario: 迁移后 PID 与迁移前一致

- **WHEN** 某板迁移到新实现后以其默认场景启动
- **THEN** 宿主机枚举到的 idProduct 与迁移前完全一致

### Requirement: USB gadget 生命周期管理

L1 SHALL 提供以下 gadget 生命周期操作，供 L3 场景层调用：

- 初始化 —— 确保 configfs 就绪、创建 gadget 目录、写入设备描述符
- 启用 —— 按 L2 能力的排序权重创建实例、调用各能力 prepare、建立 configfs 链接、绑定 UDC、校验枚举
- 停用 —— 调用各能力 stop、解绑 UDC、清理 configfs 链接
- 重配 —— 能力集合变化时先停用再启用

这些操作 SHALL 是服务内部 API，不再以命令行子命令形式对外暴露。

系统 SHALL 防止并发执行上述操作。

#### Scenario: 系统启动时自动初始化

- **WHEN** 系统启动，服务加载板级配置的默认场景
- **THEN** configfs USB gadget 被创建，该场景的能力被配置，UDC 被绑定，USB 设备可被宿主机发现

#### Scenario: 停用清理完整

- **WHEN** L3 请求停用 gadget
- **THEN** 各能力的 stop 被调用，UDC 被解绑，configfs function 链接被清理

#### Scenario: 能力集合变化时先停后启

- **WHEN** 目标能力集合与当前已启用集合不同
- **THEN** 先执行停用再执行启用，不在已绑定 UDC 的 gadget 上直接追加 function

#### Scenario: 并发请求被串行化

- **WHEN** udev 触发的重配与控制接口下发的场景切换同时到达
- **THEN** 两者被串行执行，不出现 configfs 状态错乱

### Requirement: systemd 服务配置

USB gadget 服务 SHALL 配置为：

- 在 `local-fs.target` 与 `sys-kernel-config.mount` 就绪后启动
- 由 `sysinit.target` 与 `usb-gadget.target` 两条链路拉起，保证既能尽早启动、又能在 UDC controller 就绪时兜底重启
- 具备失败重启策略与重启次数限流，使 role/VBUS/deferred probe 等短暂竞态可自愈，而真实硬件故障能保留现场

服务 SHALL 为常驻形态，以承载控制 socket 与场景状态。

#### Scenario: 服务启动顺序

- **WHEN** 系统启动进入 sysinit.target 阶段
- **THEN** 服务被自动拉起，在网络服务之前完成 USB gadget 初始化

#### Scenario: UDC 就绪时兜底

- **WHEN** 平台无 `android_usb` class 导致早期启动路径未能成功绑定，其后 UDC 设备就绪
- **THEN** `usb-gadget.target` 链路触发服务重新完成绑定

### Requirement: udev 规则

udev 规则 SHALL 在 USB 状态变化时通知常驻服务重新评估 gadget 状态，监听范围包括 `android_usb` subsystem 的 `change` 事件与 `udc` subsystem 的 `add` / `change` 事件。

通知 SHALL 为异步，且 MUST NOT 使 udev 事件处理上下文持有新拉起的进程 —— 否则 udev 在事件结束后会清理这些进程。

#### Scenario: USB 状态变化触发重新评估

- **WHEN** USB 连接状态变化（线缆插入/拔出）
- **THEN** 服务被通知并根据新状态调整 gadget

#### Scenario: 无 android_usb class 的平台

- **WHEN** 平台为 mainline dwc3，无 `android_usb` class，UDC 设备出现
- **THEN** `udc` subsystem 规则触发服务重新评估，作为 gadget 绑定的兜底路径

## ADDED Requirements

### Requirement: 平台竞态处理

L1 SHALL 实现以下平台竞态处理。每一项均对应已在真实硬件上出现过的故障，实现中 SHALL 保留说明其存在原因与对应硬件现象的注释。

| 处理 | 要求 |
|---|---|
| UDC 就绪等待 | 读取 UDC 前等待 controller 就绪，避免 deferred probe 竞态下取到空 UDC |
| UDC 绑定回读校验 | 写入 UDC 后回读校验，不以写入调用的返回值判定成功 |
| 枚举状态校验 | 绑定后校验实际枚举状态，不以绑定成功推定枚举成功 |
| 枚举恢复 | 通过翻转 D+ 上拉（soft_connect disconnect→connect）强制主机重新枚举，此过程 MUST NOT 触碰 configfs 链接或 FunctionFS |
| 无主机识别 | 枚举未完成时区分「无主机连接」与真实故障，前者保持绑定不报错 |
| 幂等写 | 写 configfs/sysfs 属性前先读取比较，值相同则跳过 |
| 描述符写入时机 | 仅在 UDC 未绑定时写入 idProduct |
| 断连恢复 | UDC 意外解绑而能力集合未变时，只重启相关 daemon，MUST NOT 清理 configfs 链接 |
| 启动幂等守卫 | 已绑定且能力集合未变化时跳过重配 |

其中「枚举恢复」与「断连恢复」两项对 configfs / FunctionFS 的禁止操作是硬约束：清理 configfs 链接会触发 `functionfs_unbind`，使持有 FunctionFS endpoint 文件描述符的 daemon 永久失效。

#### Scenario: UDC 绑定失败被检出

- **WHEN** 写入 UDC 后回读值与目标值不符
- **THEN** 判定绑定失败并报告期望值与实际值，不继续在错误状态上执行后续步骤

#### Scenario: 无主机连接不判定为故障

- **WHEN** gadget 已绑定 UDC 但未连接主机，枚举状态为未连接
- **THEN** 保持绑定状态并正常返回，不触发重试或报错

#### Scenario: 枚举恢复不破坏 FunctionFS

- **WHEN** 执行枚举恢复
- **THEN** configfs 链接与 FunctionFS 挂载保持不变，持有 endpoint 文件描述符的 daemon 不受影响

#### Scenario: 断连恢复不清理 configfs

- **WHEN** UDC 意外解绑而能力集合未变化
- **THEN** 相关 daemon 被重启，configfs 链接保持不变

#### Scenario: 重复触发不引起重配

- **WHEN** gadget 已绑定且能力集合未变，收到重复的状态变化通知
- **THEN** 不执行任何 configfs 写入或重新绑定

### Requirement: 能力排序

L1 SHALL 按 L2 能力声明的内核排序权重决定 configfs 实例的创建与链接顺序，顺序要求源自内核对 function 排列的约束。

L1 MUST NOT 硬编码具体的能力名称顺序表 —— 顺序信息由各能力自身声明。

#### Scenario: 按权重排序而非按输入顺序

- **WHEN** 场景声明的能力集合顺序与内核要求顺序不一致
- **THEN** L1 按各能力声明的排序权重重新排列后再创建实例

## REMOVED Requirements

### Requirement: adb function 实现

**Reason**: adb 不再是 gadget 核心层的内置实现，而是 L2 原子能力层中与其他能力平等的一个能力。将其保留在本 capability 会违反「L1 不含 function 名称分支」的分层约束。

**Migration**: adb 能力的行为要求迁移至新 capability `usb-capability-layer`，其中定义了 adb 的 FunctionFS 挂载、adbd 生命周期与宿主机连接验证要求。

### Requirement: hook 扩展机制

**Reason**: 该机制依赖 shell 的 `source` 语义在运行时注入函数与变量，随 shell 脚本一同移除。其承担的两项职责在新架构中由更明确的机制取代：新增 USB function 由 L2 的统一能力接口承担，配置覆盖由板级配置的分层合并承担。

**Migration**: 现有 `/etc/usbdevice.d/` 下的扩展脚本需改写。新增 function 的扩展改为实现 L2 能力接口；变量覆盖类的扩展改为板级 YAML 配置中的对应键。本次变更中 flange 仓库内无实际使用该机制的扩展脚本，仅影响下游自定义扩展。
