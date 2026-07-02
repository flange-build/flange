# amp-runtime-bringup Specification (delta)

## MODIFIED Requirements

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
