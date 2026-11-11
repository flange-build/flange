# AMP 协处理器与 rpmsg

> 阅读前提：先确认[板卡配置与硬件范围](../boards/README.md)，再阅读本专题。
> 下文接线、内核/固件行为和测试结果只覆盖注明的设备、版本与产品；单项结果不代表全部目标已验收。
> 当前构建入口见[开发指南](../development-guide.md)，新增驱动/配置见[扩展指南](../extension-guide.md)。

## 概述

Rockchip Linux master + AArch32 从核的 AMP 模型；`mode=hal|rt-thread` 均使用 rpmsg-lite 与 stock Linux rpmsg 驱动。SoC runtime profile 定义 CPU、mailbox、link-id、endpoint 和内存，避免把 RK3568 CPU3 经验硬套到 RK3506 CPU2。

| profile | Linux / 从核 | link-id / endpoint | 共享区 |
|---|---|---|---|
| RK3568 | CPU0-2 / CPU3 | `0x10` / demo 自定 | vring `0x07c00000` |
| RK3506B | CPU0-1 / CPU2 | `0x02` / `0x3003` | `0x03b00000-0x03dfffff` |

## 启动

U-Boot `CONFIG_AMP` 从 `amp` 分区读 FIT，按 ITS 的 MPIDR/load 拉起从核，再引导 Linux。RK3568 删除 Linux 的 cpu3 节点；RK3506B 删除 cpu2，并以 `no-map` 保留 `0x03e00000/1 MiB` 固件区。构建器会核对 FIT 与目标 DTS，防止 Linux 分配器覆盖运行中的 RTOS。

## RK3568 rpmsg 三约束（缺一不通）

1. **link-up 中断**：从核 `wait_for_link_up` 仅收到 Linux 首条 mailbox 中断 `MBOX0_CH3_A2B`(222) 时返回。222 须进 `&rockchip_amp` 的 `amp-irqs` 路由 cpu3，否则 Linux `gic_dist_init` 改回 cpu0。
2. **不抢 GICD**：从核 `GIC_IRQ_AMP_CTRL.cpuAff` 设非本核（gicInit=0），不重初始化 GIC 分发器，否则抢挂死。
3. **反向通道 link-id=0x10(R=0)**：rpmsg-lite 发送通道=link-id 低4位 R；stock 驱动新消息走 `rpmsg-rx`(ch0)。R=0 使新消息发 ch0 命中 stock，Linux 零改。固件与 dts `rockchip,link-id` 须同步 0x10。

## RT-Thread 的初始化约束

- link-id **须 app 自写 0x10**：厂商 `rpmsg_test.c` 用 `0x03`(R=3) 卡 link-up，弃用；`rk3568_amp_rtt_demo` 自写 echo。
- **222 须 app 补进 AMP GIC 白名单（根因）**：gicInit=0 下 `HAL_GIC_Enable(222)` 被 `GIC_AmpCheckIrqValid` 门控，仅 `HAL_GIC_Init` 经 `irqsCfg` 进 `ampValid` 的 IRQ 可使能，BSP 仅 `COMMON_TEST` flag 下含 222。app 在 rpmsg init 前再调一次 `HAL_GIC_Init`（只含 222、`cpuAff` 非本核）补白名单。约束2 由 BSP 默认满足。

## RK3506B 差异

CPU2 走 `mailbox2` / IRQ 176，BSP 已有对应路由，不需要 IRQ 222 workaround。[rk3506 AMP UART4 RPMsg demo](rk3506-amp-uart4-rpmsg-demo.md) 的 runtime header 由 `FINAL_CONFIG` 生成；2026-07-15 已确认 Linux channel、UART4/MSH 与多轮 binary echo 通过。

## 易踩坑

link-id 两侧不同步 → 握手崩；接收恒走 A2B ch3（物理 cpu_id）与 link-id 无关；辨症：`MBOX0 A2B_STATUS ch3` 起不消费=222 未使能（devmem 可读）。
