## MODIFIED Requirements

### Requirement: 目标板 Linux DTS 接入 AMP 通信节点

启用 AMP 的 target SHALL 选择包含以下内容的专用 DTS：AMP reserved-memory、
`rockchip-amp`、`rockchip,rpmsg`、已启用 mailbox、从 Linux CPU 列表删除的 AMP core，以及不被
Linux 占用的 AMP console UART。该 DTS MAY 已存在于指定 kernel branch，也 MAY 由 board patch
新增；若内核已提供精确匹配的 DTS，flange SHALL 直接选用而不得复制或改写一份同名协议。

reserved-memory、从核 load/MPIDR、RPMsg base/size、mailbox/link-id 和 UART 资源 SHALL 与
FINAL_CONFIG 及 AMP FIT 一致。builder SHALL 根据 `kernel.arch`、`kernel.dts_dir` 和目标 DTS
include 链执行交叉校验，不得写死 RK3568/ARM64 路径。地址或资源不一致 MUST 使构建失败。

#### Scenario: 编出的 dtb 含 AMP 节点
- **WHEN** 构建启用 AMP 的 target 并反编译 DTB
- **THEN** 含 `compatible=rockchip,rpmsg`、AMP reserved-memory 和 `rockchip-amp`
- **AND** 相关 mailbox 节点为 `okay`

#### Scenario: AMP 从核的 cpu 节点被摘出 Linux
- **WHEN** 反编译启用 AMP 的 DTB 或在目标板查看 CPU 枚举
- **THEN** 分给 AMP 的 CPU 节点不属于 Linux
- **AND** Linux CPU 数量等于 SoC 总核数减去配置的 AMP 核数

#### Scenario: 非 AMP product 不受专用 DTS 影响
- **WHEN** 某板同时提供非 AMP product 并构建该 product
- **THEN** 不选择 AMP DTS 且不删除 Linux CPU

#### Scenario: 内核已有精确 AMP DTS 时直接复用
- **WHEN** 指定 kernel branch 已包含 board 配置声明的 AMP DTS
- **THEN** kernel builder 直接构建该 DTS
- **AND** board 不增加复制该 DTS 的 patch

#### Scenario: DTS 地址与 amp 固件一致
- **WHEN** 比较 DTS、FINAL_CONFIG 与 amp FIT 的 reserved-memory/RPMsg/load 数据
- **THEN** 对应地址、大小、CPU 与 link-id 一致
- **AND** CPU2 firmware `0x03e00000/0x00100000` 具有 `no-map` reserved-memory

#### Scenario: Linux 不管理 CPU2 firmware 内存
- **WHEN** 目标板启动后读取 `/proc/iomem` 与 reserved-memory sysfs
- **THEN** `0x03e00000-0x03efffff` 不属于 Linux System RAM

#### Scenario: DTS 与配置不一致时被拦截
- **WHEN** DTS include 链中的 AMP 数据与 FINAL_CONFIG 不一致
- **THEN** 构建失败并指出字段、DTS 值与配置值

### Requirement: AMP↔Linux rpmsg 链路建立与双向收发

flange 交付的 AMP product SHALL 通过一个按 SoC 定义的 runtime profile 统一 DTS、固件与
rpmsg-lite port。profile MUST 至少声明 AMP CPU、Linux master CPU、link-id、mailbox 实例/通道、
mailbox IRQ、RPMsg memory、endpoint 和 GIC 初始化策略。固件与 DTS MUST 消费相同语义值，Linux
RPMsg 驱动保持 target kernel 的 stock 实现。

所有 profile SHALL 满足：从核不重新初始化由 Linux 管理的 GIC distributor；mailbox IRQ 可在
从核上被使能；`rpmsg_lite_wait_for_link_up` 成功；从核发送 name-service announce；Linux 可创建
字符 endpoint 并完成双向数据。

RK3568 profile SHALL 保持现有 CPU3、`link-id=0x10`、MBOX0_CH3_A2B/INTID 222 和 RT-Thread
app 增量 GIC 白名单行为。RK3506 profile SHALL 使用 CPU2、`link-id=0x02`、DTS 中的
mailbox0/mailbox2 与 INTID 176/RK3506 `MAILBOX_BB_2_IRQn` 路由；它 SHALL NOT 套用
RK3568 的 link-id 或 INTID 222 workaround。

#### Scenario: 从核 link-up 成功
- **WHEN** AMP 固件运行且 Linux RPMsg master 初始化完成
- **THEN** 从核 console 打印 `link up` 与 endpoint `announced`

#### Scenario: Linux 建出从核通告的 rpmsg 通道
- **WHEN** 从核执行 name-service announce
- **THEN** Linux `/sys/bus/rpmsg/devices` 与 dmesg 出现对应通道

#### Scenario: 端到端双向收发
- **WHEN** Linux 经 `/dev/rpmsg_ctrlN` 创建 endpoint 并写入数据
- **THEN** 从 `/dev/rpmsgN` 读回从核响应

#### Scenario: RK3568 runtime 行为保持不变
- **WHEN** 构建和启动既有 RK3568 RT-Thread AMP product
- **THEN** 继续使用 CPU3、link-id `0x10`、INTID 222 与既有 GIC 白名单处理
- **AND** RPMsg echo 回归通过

#### Scenario: RK3506 runtime 使用 SoC 专用 profile
- **WHEN** 构建和启动 RK3506B RT-Thread AMP product
- **THEN** 固件和 DTS 均使用 CPU2、link-id `0x02`、mailbox0/mailbox2 与 RK3506 mailbox IRQ
- **AND** 不注入 RK3568 的 INTID 222 配置

#### Scenario: 两种 mode 使用同一板级协议
- **WHEN** 某 target 同时提供 HAL 与 RT-Thread mode
- **THEN** 两者共用该 target 的 DTS、runtime profile 与 stock Linux driver
- **AND** 仅 amp partition 内的从核 firmware 内容不同

## ADDED Requirements

### Requirement: RK3506B AMP console 固定为 UART4

ATK-RK3506B 的 DTS、RT-Thread BSP 与 app SHALL 一致使用 UART4、
`RM_IO27_TX/RM_IO28_RX`、UART4 IRQ 和 1500000 8N1。Linux SHALL 不初始化或复用该 UART pinmux。

#### Scenario: UART4 三方配置一致
- **WHEN** 检查目标 DTB、RT-Thread `.config` 和 app 初始化代码
- **THEN** 三者均选择 UART4 与相同 pinmux/baud rate

#### Scenario: 冷启动日志可见
- **WHEN** 从 SPI NAND 冷启动并监听 UART4
- **THEN** 在 RPMsg link-up 前看到 RT-Thread banner 和 CPU2 启动日志
- **AND** link-up 后 MSH 可交互
