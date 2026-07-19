## ADDED Requirements

### Requirement: RK3506 实时核运行主机编译后的 FTS 静态计划

系统 SHALL 在主机或 Web 构建环境完成 FTS 解析、语义和安全验证，并把生成的静态 Swift
计划链接进 CPU2 RT-Thread 固件。实时核 MUST NOT 解析 FTS 文本、加载工作区布局或依赖
Foundation/文件系统完成控制调度。

#### Scenario: 编排结果进入固件

- **WHEN** 用户从 Web 导出通过验证的 FTS 并构建 fluxion product
- **THEN** AMP archive 包含该 FTS 生成的静态 Runtime plan，CPU2 初始化时核对计划、
  配置和 board capability 后执行

#### Scenario: 工作区布局不进入固件

- **WHEN** 用户只移动节点、缩放画布或固定示波器而不改变 FTS
- **THEN** 生成的 AMP 算法产物保持不变

### Requirement: Runtime 必须由单一控制线程独占

RPMsg、遥测和中断上下文 MUST NOT 并发修改 Swift Runtime。命令 SHALL 通过固定容量队列
在控制 tick 边界应用；遥测 SHALL 通过 latest snapshot 向低优先级任务传递。快环 MUST
NOT 执行 RPMsg 阻塞发送、JSON、文件、动态内存或网络 I/O。

#### Scenario: RPMsg 命令与快环并发到达

- **WHEN** RPMsg worker 收到合法 set-Iq，同时控制线程执行 fastTick
- **THEN** worker 只入队，控制线程在后续 tick 边界按序应用并返回 applied ACK

#### Scenario: 遥测拥塞

- **WHEN** Linux 来不及读取遥测
- **THEN** CPU2 覆盖或丢弃旧遥测并累计 drop counter，不延迟控制 tick

### Requirement: 控制链必须有租约并失败关闭

控制端 SHALL 先获取有界 deadman lease，并周期续租。CPU2 只接受当前 session、合法序号和
范围内的高层命令。租约超时、session 不匹配、显式 disarm、RPMsg 断开、协议错误或硬件故障
MUST 停止 Runtime、锁存相应状态并调用独立 board force-safe。

#### Scenario: Linux 控制端失联

- **WHEN** 当前租约在 deadline 前未续租
- **THEN** CPU2 不等待下一条网络消息，立即进入安全态并拒绝旧 session 后续命令

#### Scenario: Web 尝试裸 PWM

- **WHEN** `/control` 收到裸 duty/MMIO/寄存器写请求
- **THEN** Linux bridge 拒绝请求且不向 RPMsg 转发

### Requirement: RPMsg 线协议固定有界且与语言 ABI 解耦

控制和遥测 SHALL 使用总长不超过 496 字节的 FXT1 小端二进制帧。header SHALL 包含
magic、version、type、flags、sequence、request_id、payload_len、reserved 和 CRC32。
系统 MUST NOT 直接 memcpy Swift enum、Bool、Runtime context 或 C 编译器填充结构作为线
协议。每条控制 request MUST 返回关联 request_id 的 ACK。

成对 D/Q 给定 MUST 使用 `REFERENCE_SET=6` 的单个 16 字节 payload（session、kind、
reserved、D、Q）。目标端 MUST 在一个控制边界内完成一次 capability/lease/range 校验、
一次 Runtime 事务和一个 ACK；MUST NOT 用两条标量 request 冒充原子 D/Q，也 MUST NOT
在第二个分量失败时保留第一个分量。D/Q current 与 D/Q voltage 的 atomic capability MUST
分别声明，未声明对应 kind 时 Linux bridge 和 Web 均 SHALL 失败关闭。

#### Scenario: CRC 或长度非法

- **WHEN** CPU2 或 Linux 收到 CRC 不匹配、payload_len 越界或未知必要版本的帧
- **THEN** 丢弃该帧、记录协议错误并保持/进入安全状态

#### Scenario: 原子 D/Q 给定失败

- **WHEN** `REFERENCE_SET` 的 reserved 非零、D/Q 非 finite、向量越界、sequence 重放、
  lease 失效或对应 atomic capability 缺失
- **THEN** 目标端拒绝整笔 request、返回单个关联 ACK，D/Q 两个事实源都保持原值

### Requirement: Web 遥测和控制端点必须分离

Linux bridge SHALL 复用 `fluxion.telemetry/v1` 提供 `/healthz` 和只读 `/telemetry`；
控制 SHALL 通过独立 `/control`，并具有 request ID、ACK、租约和权限检查。Web MUST NOT
直接访问 `/dev/rpmsg*`。

#### Scenario: 现有工作台连接实板

- **WHEN** 工作台先核对 `/healthz` 身份后连接 `/telemetry`
- **THEN** bridge 发布与现有信号名兼容的遥测帧，节点和示波器可直接观测

### Requirement: 未适配真实功率板时目标端必须拒绝驱动

production board hooks SHALL 显式声明电流、转子、PWM、fault 和 power-stage capability。
任一必需 hook 未实现、拓扑不匹配或 `powerStageConnected=false` 时，Runtime 初始化或 start
MUST 失败并保持 PWM safe。loopback profile 必须声明 simulated，不能冒充真实设备。

#### Scenario: 只有 ATK 主板没有功率板接线定义

- **WHEN** 固件使用默认 production hooks 启动
- **THEN** 能完成 CPU2/RPMsg/遥测诊断，但 start 被拒绝且所有 PWM 输出保持安全
