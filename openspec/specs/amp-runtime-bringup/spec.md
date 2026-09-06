# amp-runtime-bringup Specification

## Purpose

定义 AMP 从核在真实硬件上跑起来的契约：U-Boot 怎么拉起从核、Linux DTS 怎么接入通信节点、rpmsg 链路怎么建立，以及 console UART 在板级、DTS、固件三方之间如何保持一致。

## Requirements
### Requirement: U-Boot 启用 AMP loader 从 amp 分区拉起从核

flange SHALL 为 Rockchip bootloader 提供启用 AMP 的配置（经 `bootloader.defconfig` 的 **raw inline option** 机制——board 层用 `+defconfig:<product>` 追加 `CONFIG_AMP=y` / `CONFIG_ROCKCHIP_AMP=y`，bootloader builder 把含 `=` 的项 append 进 `.config` 后 `make olddefconfig` 归一化；配置增加走配置、不走 patch），同时启用 `CONFIG_AMP=y` 与 `CONFIG_ROCKCHIP_AMP=y`（其依赖 `ROCKCHIP_SMCCC`、`RKIMG_BOOTLOADER` 在目标 SoC 上已满足，`olddefconfig` 据 Kconfig 依赖保留之）。`bootloader.defconfig` SHALL 支持单字符串或 list 两形态（list 中含 `=`/`# CONFIG_` 的项为 raw option、其余为 defconfig/fragment make 目标），使该机制与 `kernel.defconfig` 一致。启用后 U-Boot SHALL 按分区名 `amp` 读取 FIT、把各核固件搬到其 `load` 地址、用 SMC/PSCI 拉起从核，并（amp_linux.its 路线）继续引导 Linux 到主核。两个 config SHALL 成对启用（仅开 `CONFIG_AMP` 会因 `arm64_switch_amp_pe`/`amp_cpus_on` 无定义而链接失败）。

#### Scenario: u-boot 配置含成对 AMP 选项

- **WHEN** 构建出目标板 u-boot 并查看其 `.config`
- **THEN** 同时含 `CONFIG_AMP=y` 与 `CONFIG_ROCKCHIP_AMP=y`

#### Scenario: 无 amp 分区时正常启动不受影响

- **WHEN** 启用 `CONFIG_AMP` 但设备无 amp 分区（或 amp 分区为空）
- **THEN** `amp_cpus_on()` 因 `part_get_info_by_name("amp")` 失败而早退（`-ENODEV`），主系统照常启动 Linux

### Requirement: 目标板 Linux DTS 接入 AMP 通信节点

启用 AMP 的 target SHALL 选择包含以下内容的专用 DTS：AMP reserved-memory、
`rockchip-amp`、`rockchip,rpmsg`、已启用 mailbox、从 Linux CPU 列表删除的 AMP core，以及不被
Linux 占用的 AMP console UART。该 DTS MAY 已存在于指定 kernel branch，也 MAY 由 board patch
新增；若内核已提供精确匹配的 DTS，flange SHALL 直接选用而不得复制或改写一份同名协议。

reserved-memory、从核 load/MPIDR、RPMsg base/size、mailbox/link-id 和 UART 资源 SHALL 与
FINAL_CONFIG 及 AMP FIT 一致。builder SHALL 根据 `architecture.kernel`、`kernel.device_tree.directory` 和目标 DTS
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

### Requirement: 内核暴露 rpmsg 字符设备供用户态通信

需要 amp 通信的 SoC 内核配置 SHALL 追加 `CONFIG_RPMSG_CHAR=y` 与 `CONFIG_RPMSG_CTRL=y`（经 `kernel.defconfig` 的 raw inline 机制注入）。理由：现有 defconfig 虽已开 `RPMSG_ROCKCHIP_MBOX`/`RPMSG_VIRTIO`，但没有任何选项会 select 这两项，缺它们则无 `/dev/rpmsg_ctrlN`、`/dev/rpmsgN`，用户态 app 无法直接收发。

#### Scenario: 内核 .config 含 rpmsg 字符设备

- **WHEN** 构建目标板内核并查看 `.config`
- **THEN** 含 `CONFIG_RPMSG_CHAR=y` 与 `CONFIG_RPMSG_CTRL=y`

#### Scenario: 运行时暴露 rpmsg 字符设备（上板验证）

- **WHEN** amp 固件运行、Linux 起来后在目标设备上查看 `/dev`
- **THEN** 存在 `/dev/rpmsg_ctrlN`，且用户态经 `RPMSG_CREATE_EPT_IOCTL` 创建端点后出现 `/dev/rpmsgN`

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

### Requirement: AMP 从核 console UART 按板选择并保持三方一致

AMP runtime SHALL 支持目标板按硬件引出情况选择从核 console UART。若目标板的 AMP console 不使用
默认 UART4，board 专用 AMP dts、HAL app、RT-Thread BSP/app MUST 对同一个 UART 实例、pin mux、
clock、IRQ 与 baud rate 达成一致。

对 Orange Pi CM4，AMP console MUST 使用 UART7_M2：

- dts `rockchip-amp` 使用 `SCLK_UART7` / `PCLK_UART7`
- dts `rockchip-amp.pinctrl-0` 使用 `uart7m2_xfer`
- dts `rockchip-amp.amp-irqs` 使用 `UART7_IRQn` / INTID 155 作为 console IRQ
- HAL app 使用 `UART7`、`g_uart7Dev`、`HAL_PINCTRL_IOFuncSelForUART7(IOFUNC_SEL_M2)`，
  baud rate 保持 1500000
- RT-Thread BSP/app 使用 `RT_USING_UART7`、console device `uart7`、UART7_M2 pin mux、
  `UART7_IRQn`，baud rate 保持 115200

对既有 `tspi-rk3566`，AMP console MUST 保持 UART4_M1 行为不变。

#### Scenario: Orange Pi CM4 HAL runtime 的 UART 配置一致

- **WHEN** 构建 `orangepi-cm4-amp-release`
- **THEN** board AMP dts 中 `rockchip-amp` 的 clock/pinctrl/console IRQ 指向 UART7_M2
- **AND** HAL app 初始化 UART7_M2
- **AND** HAL app baud rate 为 1500000
- **AND** HAL app 的 console IRQ 配置使用 `UART7_IRQn`

#### Scenario: Orange Pi CM4 RT-Thread runtime 的 UART 配置一致

- **WHEN** 构建 `orangepi-cm4-amp-rtt-release`
- **THEN** board AMP dts 中 `rockchip-amp` 的 clock/pinctrl/console IRQ 指向 UART7_M2
- **AND** RT-Thread app 的 `.config` 片段选择 `RT_USING_UART7`
- **AND** RT-Thread console device 为 `uart7`
- **AND** RT-Thread BSP 为 UART7_M2 配置 pin mux、board 描述与 `UART7_IRQn`
- **AND** RT-Thread UART7 baud rate 为 115200

#### Scenario: tspi-rk3566 仍保持 UART4_M1

- **WHEN** 构建或解析 `tspi-rk3566-amp-release` 与 `tspi-rk3566-amp-rtt-release`
- **THEN** 其 AMP dts、HAL app 与 RT-Thread 默认配置仍使用 UART4_M1
- **AND** 不要求 `tspi-rk3566` 切换到 UART7_M2

### Requirement: 板级 console UART 变更不改变 rpmsg 协议

AMP console UART 的板级差异 MUST NOT 改变 Linux↔AMP rpmsg 通信协议。Orange Pi CM4 的 HAL 与
RT-Thread AMP product SHALL 继续使用现有 rpmsg 约束：

- `rockchip,link-id = <0x10>`
- 从核 endpoint 名称为 `rpmsg-ap3-ch0`
- 从核 endpoint address 为 `0x3003`
- `MBOX0_CH3_A2B_IRQn` / INTID 222 路由到 cpu3
- Linux 内核 rpmsg 驱动保持 stock，不为 Orange Pi CM4 增加专用 patch

#### Scenario: Orange Pi CM4 HAL 与 RT-Thread 共用 rpmsg 协议

- **WHEN** 构建 `orangepi-cm4-amp-release` 与 `orangepi-cm4-amp-rtt-release`
- **THEN** 二者 board AMP dts 的 `rockchip,link-id` 均为 `0x10`
- **AND** 二者从核 app 均通告 endpoint `rpmsg-ap3-ch0`
- **AND** 二者从核 app 均使用 endpoint address `0x3003`
- **AND** 二者 dts 的 `amp-irqs` 均包含 `MBOX0_CH3_A2B_IRQn` / INTID 222 路由到 cpu3

#### Scenario: Orange Pi CM4 上板 rpmsg 双向 echo 成功

- **WHEN** Orange Pi CM4 启动任一 AMP product 且 Linux 侧创建匹配 `rpmsg-ap3-ch0` 的
  `/dev/rpmsgN` 端点
- **THEN** 向 `/dev/rpmsgN` 写入数据后可读回从核 echo
- **AND** Linux dmesg 显示创建对应 rpmsg channel

### Requirement: RT-Thread AMP 保持单核运行并提供早期启动日志

RK3568 RT-Thread AMP SHALL 作为 cpu3 上的单核 RTOS 实例运行，MUST NOT 启用
`RT_USING_SMP` 或尝试通过 PSCI 拉起 Linux 所属 CPU。UART console 驱动 SHALL 在
device open/close 生命周期向 Rockchip UART 底层发送当前 SDK 对应的
`RT_DEVICE_CTRL_OPEN/CLOSE` 通知。

标准 RT-Thread banner/version 与 app 的 cpu 启动日志 MUST 在 RPMsg link-up 之前通过
板级 AMP console 输出；MSH 启动后手工执行 `version` 成功不能替代该早期日志验收。

#### Scenario: 启动阶段输出完整且顺序正确

- **WHEN** 刷写并冷启动 RK3568 RT-Thread AMP product
- **THEN** console 先输出 RT-Thread banner、版本和 app cpu 启动日志
- **AND** 随后输出 RPMsg remote init、link-up 与 endpoint announce
- **AND** MSH 可交互

#### Scenario: 最终固件不包含 SMP 拉核行为

- **WHEN** 检查最终 `.config` 并启动固件
- **THEN** `RT_USING_SMP` 未启用
- **AND** RT-Thread 不尝试启动 cpu0、cpu1 或 cpu2

### Requirement: RT-Thread 4.1.1 rpmsg 与中断 glue 使用当前 API

RT-Thread AMP app 调用 `rpmsg_lite_wait_for_link_up` 时 SHALL 显式传入 `RL_BLOCK`。
RK3568 rpmsg platform 的中断路由 SHALL 使用当前 HAL GIC route API，并保持既有
MBOX0_CH3_A2B IRQ、link-id 0x10 和 GIC 白名单约束不变。

#### Scenario: RT-Thread 4.1.1 构建并完成 RPMsg echo

- **WHEN** 使用同步后的 RT-Thread 4.1.1 与 Rockchip HAL SDK 构建并上板
- **THEN** app 不因旧版 rpmsg-lite 或 GIC route API 编译失败
- **AND** Linux 创建 `rpmsg-ap3-ch0` 后双向 echo 成功

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
