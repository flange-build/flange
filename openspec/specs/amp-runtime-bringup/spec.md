# amp-runtime-bringup Specification

## Purpose
TBD - created by archiving change add-amp-firmware-support. Update Purpose after archive.
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

flange SHALL 为目标板提供一个**专用 AMP dts 文件**（经 board kernel patch 新增到内核树，由 amp product 的 `kernel.dts` 选用），内容为基础板 dts 加三类 AMP 改动：(a) `#include "rk3568-amp.dtsi"`（或等价内联）接入 `reserved-memory`（amp_shmem / rpmsg / rpmsg_dma / mcu 段）、`rockchip-amp`（amp-cpus entry + amp-irqs）、`rpmsg`（`rockchip,rpmsg` + `mboxes` + `memory-region`）并使能 `&mailbox`（status = okay）；(b) `/delete-node/ &<amp-core>;` 把分给 AMP 的 cpu 节点（tspi-rk3566 为 cpu3）从 Linux 摘掉，使 Linux 不去 online 该核；(c) 确保 AMP 从核 console 所用 UART（默认 UART4）不被 Linux 占用。reserved-memory 与 amp-cpus entry 地址 SHALL 与 amp 固件内存布局（SHMEM_BASE / LINUX_RPMSG_BASE / 从核 load 地址）一致。改动 SHALL 走独立 dts 文件 + product 选用，SHALL NOT 写成会改基础板主 dts 的 board patch（patch 按板对所有 product 生效，会污染非 amp product）；也 SHALL NOT 走运行时 overlay（目标板 extlinux 默认不应用 overlay）。因 DTS 走静态 patch、无法在构建期消费 SoC 内存布局常量（与 build.sh/.its 两腿由构建器注入不同），flange SHALL 提供一个构建期/校验期交叉比对：把 patch 内的 reserved-memory / amp-cpus entry 地址与 SoC 内存布局常量逐项比对，不一致 SHALL 使构建/校验失败——以此把 DTS 这条手工腿纳入内存布局单一事实源的一致性保障，避免「改了常量忘改 patch」无人拦截。

#### Scenario: 编出的 dtb 含 AMP 节点

- **WHEN** 用 amp product（如 `tspi-rk3566-amp`）构建内核并反编译其 dtb
- **THEN** 含 `compatible = "rockchip,rpmsg"` 节点、四段 AMP `reserved-memory`、`rockchip-amp` 节点
- **AND** `mailbox` 节点 `status` 为 `okay`

#### Scenario: AMP 从核的 cpu 节点被摘出 Linux

- **WHEN** 用 amp product 构建并反编译 dtb，或上板执行 `nproc`/`cat /proc/cpuinfo`
- **THEN** dtb 中分给 AMP 的 cpu 节点（tspi-rk3566 为 `cpu@300`/cpu3）不存在
- **AND** Linux 仅枚举 3 个 CPU（cpu0/1/2）

#### Scenario: default product 不受 AMP dts 影响

- **WHEN** 用 `default` product（非 amp）构建内核
- **THEN** 其 dtb 不含 AMP 节点、cpu 节点齐全（4 核），不选用 amp dts 文件

#### Scenario: DTS 地址与 amp 固件一致

- **WHEN** 比较 DTS 的 reserved-memory/amp-cpus entry 地址与 amp 固件注入的 SHMEM/LINUX_RPMSG/load 地址
- **THEN** 对应段地址逐字节一致（同一内存布局事实源）

#### Scenario: DTS 地址与 SoC 常量不一致时被拦截

- **WHEN** board kernel patch 内的 reserved-memory/amp-cpus 地址与 SoC 内存布局常量不一致
- **THEN** 构建期/校验期交叉比对失败，给出明确错误（指出哪段地址不匹配）

### Requirement: 内核暴露 rpmsg 字符设备供用户态通信

需要 amp 通信的 SoC 内核配置 SHALL 追加 `CONFIG_RPMSG_CHAR=y` 与 `CONFIG_RPMSG_CTRL=y`（经 `kernel.defconfig` 的 raw inline 机制注入）。理由：现有 defconfig 虽已开 `RPMSG_ROCKCHIP_MBOX`/`RPMSG_VIRTIO`，但没有任何选项会 select 这两项，缺它们则无 `/dev/rpmsg_ctrlN`、`/dev/rpmsgN`，用户态 app 无法直接收发。

#### Scenario: 内核 .config 含 rpmsg 字符设备

- **WHEN** 构建目标板内核并查看 `.config`
- **THEN** 含 `CONFIG_RPMSG_CHAR=y` 与 `CONFIG_RPMSG_CTRL=y`

#### Scenario: 运行时暴露 rpmsg 字符设备（上板验证）

- **WHEN** amp 固件运行、Linux 起来后在目标设备上查看 `/dev`
- **THEN** 存在 `/dev/rpmsg_ctrlN`，且用户态经 `RPMSG_CREATE_EPT_IOCTL` 创建端点后出现 `/dev/rpmsgN`

### Requirement: AMP↔Linux rpmsg 链路建立与双向收发

flange 交付的 amp product（dts + amp 从核固件 + 内核）SHALL 共同满足 rpmsg-lite 从核与 Linux master 之间「链路握手 + name-service 通告 + 双向数据」的三项约束，缺一则链路不通（上板表现为从核卡 `rpmsg_lite_wait_for_link_up`，或 link-up 成功但 Linux 无对应 rpmsg 通道）。三约束 mode 无关，但旋钮位置随 mode 不同：`hal` 在 amp app 的 `main.c`，`rt-thread` 在 BSP 的 `board/common/`。

**(a) rpmsg 邮箱中断路由到从核（DTS amp-irqs + 固件侧路由）。** 从核 `rpmsg_lite_wait_for_link_up` 死等本核 RAM 的 `link_state`，它仅在从核收到 Linux 发来的首条 mailbox 中断——MBOX0 通道3 A2B 方向，INTID 222 / GIC SPI 190——经 ISR 置 1（与共享内存/cache 无关）。该 IRQ SHALL 列入 `rockchip-amp` 的 `amp-irqs` 并路由到 AMP 核（tspi-rk3566 = cpu3）；否则 Linux `gic_dist_init`（irq-gic-v3）会把未列入 amp-irqs 的 SPI 的 GICD_IROUTER 强制改回 boot CPU(cpu0)、盖掉从核自设路由，使从核永久阻塞。**该 DTS amp-irqs 腿 mode 无关，hal 与 rt-thread 共用同一 board dts。** 固件侧亦 SHALL 把 222 路由到本核：`hal` 由 amp app `irqsConfig[]` 提供；`rt-thread` 由 BSP `board/common/board_base.c` 的 `irqsConfig[]` 在 Linux-rpmsg Kconfig 选项（如 `RT_USING_COMMON_TEST_LINUX_RPMSG_LITE`）下提供，故 rt-thread app 的 `.config` SHALL 启用该选项。

**(b) 从核不接管 GIC 分发器。** amp 从核固件的 `GIC_IRQ_AMP_CTRL.cpuAff`/`defRouteAff` SHALL 设为**非本核**（Linux master 所在 cpu0），使 `HAL_GIC_Init` 判定 `gicInit=0`——从核仅等待 Linux 配置好 AMP 路由后使能自身 IRQ，SHALL NOT 重初始化 GIC 分发器。设为本核会令 `gicInit=1`、从核与 Linux 抢 GICD 致挂死。旋钮：`hal` 在 amp app `main.c`（早期默认 `(3,0)` 须改 cpu0）；`rt-thread` 在 BSP `board/common/board_base.c` 的 `irqConfig`，**厂商 BSP 默认即 `cpuAff = CPU_GET_AFFINITY(0,0)`、`defRouteAff = CPU_GET_AFFINITY(0,0)`，已满足，无需改**。

**(c) 反向通道（从核→Linux 新消息）经 link-id 命中 stock 驱动，内核 rpmsg 驱动保持 stock。** rpmsg-lite `platform_notify` 用 `RL_GET_R_CPU_ID(link-id)`（低4位 R）作从核发送的 mailbox 通道号；stock `rockchip_rpmsg_mbox` 把"新消息"通道定为 `rpmsg-rx`(ch0)→`rk_rpmsg_rx_callback`→vq[0]。故 link-id 低4位(R) SHALL 取 **0**，使从核把新消息发到 ch0、命中 stock rx 回调；高4位(M) 取任意 ≠ 从核物理 cpu 的值。固件的 `RL_PLATFORM_SET_LINK_ID(M,R)` 与 board dts override 的 `rockchip,link-id` SHALL 同步为该值（如 **0x10**，M=1/R=0）。旋钮：`hal` 在 amp app `main.c` 的 `LINK_ID_M/R`；`rt-thread` **在 amp app `main.c` 自写** `RL_PLATFORM_SET_LINK_ID(1,0)=0x10`——**上板修正：厂商 `rpmsg_test.c` 的 Linux-rpmsg 测试自定义 `MASTER_ID=0`、`remote_id=cpu3` → `0x03`（R=3），与 stock 驱动（新消息 ch0）及 dts 的 0x10 均不符（卡 `wait_for_link_up`），故 SHALL NOT 直接用厂商测试；rt-thread app SHALL 自写 rpmsg echo 并取 link-id 0x10**。flange SHALL NOT 为此 patch 内核 rpmsg 驱动（两 mode 共用 100% stock 驱动，与上游 radxa/rockchip-linux 一致）。

**(d) rt-thread：222 SHALL 由 app 补进 AMP GIC 白名单。** AMP 模式（`gicInit=0`）下 `HAL_GIC_Enable(irq)` 受 `GIC_AmpCheckIrqValid()` 门控——仅 `HAL_GIC_Init` 经 `irqsCfg` 进过 `ampValid` 白名单的 IRQ 才可本核使能。`hal` app 的 `irqsConfig[]` 已含 `MBOX0_CH3_A2B_IRQn`(222)；`rt-thread` BSP `board_base.c` 仅在 `RT_USING_COMMON_TEST_LINUX_RPMSG_LITE` flag 下才含 222（而该 flag 会拉起厂商测试于错误 link-id）。故不开该 flag 时，rt-thread app SHALL 在 `rpmsg_lite_remote_init` 之前调用 `HAL_GIC_Init(&cfg)`（`cfg.irqsCfg` 仅含 222、`cpuAff` 取非本核以保持 gicInit=0）增量补进白名单——否则 rpmsg-lite 的 `HAL_GIC_Enable(222)` 静默返回 `HAL_INVAL`，从核收不到 Linux kick、永卡 `wait_for_link_up`（现象：`MBOX0 A2B_STATUS ch3` 位置起不被消费）。

#### Scenario: 从核 link-up 成功

- **WHEN** amp 固件运行、Linux 起来后查看从核 console（UART4）
- **THEN** 打印 `rpmsg: link up` 与端点 `announced`（说明 `wait_for_link_up` 已返回、收到了 INTID 222 邮箱中断）

#### Scenario: Linux 建出从核通告的 rpmsg 通道

- **WHEN** 从核 `rpmsg_ns_announce` 后在 Linux 查看 `/sys/bus/rpmsg/devices`
- **THEN** 出现从核通告的通道（地址与固件端点一致），dmesg 含 `creating channel`

#### Scenario: 端到端双向收发

- **WHEN** 经 `/dev/rpmsg_ctrl0` 创建匹配该通道的端点得 `/dev/rpmsgN`，向其写入数据
- **THEN** 读回从核 echo（双向数据路径通）

#### Scenario: rt-thread app 满足约束 (b)/(c)/(d)（上板实测）

- **WHEN** 以 `mode=rt-thread` 构建并上板
- **THEN** 约束 (b) `gicInit=0` 由 BSP `board_base.c` 的 `irqConfig.cpuAff=cpu0` 默认满足
- **AND** 约束 (c) link-id 由 amp app `main.c` 自写 `SET_LINK_ID(1,0)=0x10`（与 dts 0x10 一致），**非**厂商测试的 0x03
- **AND** 约束 (d) app `main.c` 在 rpmsg init 前 `HAL_GIC_Init(&amp_extra_gic)` 把 222 补进 AMP GIC 白名单
- **AND** 上板结果：从核 UART4 打印 `link up!`+`announced`，Linux `dmesg` 出现 `creating channel rpmsg-ap3-ch0 addr 0x3003`

#### Scenario: 两 mode 共用同一 board dts 与 stock 内核驱动

- **WHEN** 在 hal 与 rt-thread 两 product 间切换并构建 image
- **THEN** 二者用同一份 board amp dts（amp-irqs、`rockchip,link-id`、reserved-memory、amp-cpus entry）与同一份未 patch 的内核 rpmsg 驱动
- **AND** 仅 amp.img 的从核固件内容不同（CMake firmware vs scons rtthread）

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

