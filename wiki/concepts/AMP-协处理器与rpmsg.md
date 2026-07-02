---
title: AMP 协处理器与 rpmsg
type: concept
status: stable
sources:
  - components/board/tspi-rk3566/patches/kernel/0003-add-tspi-rk3566-amp-dts.patch
  - components/app/rk3568_amp_demo/src/main.c
  - components/app/rk3568_amp_rtt_demo/applications/main.c
  - components/board/tspi-rk3566/config.py
  - components/platform/rockchip/rk3566/config.py
related:
  - "[[amp 构建器]]"
  - "[[tspi-rk3566]]"
  - "[[rockchip 平台]]"
  - "[[U-Boot 启动链]]"
updated: 2026-07-02
---

## TL;DR

cpu3 切 AArch32 跑从核（`mode=hal` 裸机 / `mode=rt-thread` RTOS，均 rpmsg-lite），Linux 跑 3 核当 master，经 rpmsg + mailbox + 共享 vring(0x7c00000) 通信。从核 console=UART4。两 mode 共用同一 amp dts 与同一 stock 内核驱动（零 fork）。

## 启动

U-Boot `CONFIG_AMP`（board `bootloader.+defconfig:amp`）从 `amp` 分区读 FIT、按 `amp-cpus` entry(0x07000000) PSCI 拉起 cpu3，再引导 Linux 到 cpu0；amp dts（patch 0003）`/delete-node/ &cpu3`，Linux 只 online cpu0-2。

## rpmsg 链路三约束（缺一不通，上板 /dev/rpmsg0 echo 验证）

1. **link-up 中断**：从核 `wait_for_link_up` 仅收到 Linux 首条 mailbox 中断 `MBOX0_CH3_A2B`(222) 时返回。222 须进 `&rockchip_amp` 的 `amp-irqs` 路由 cpu3，否则 Linux `gic_dist_init` 改回 cpu0。
2. **不抢 GICD**：从核 `GIC_IRQ_AMP_CTRL.cpuAff` 设非本核（gicInit=0），不重初始化 GIC 分发器，否则抢挂死。
3. **反向通道 link-id=0x10(R=0)**：rpmsg-lite 发送通道=link-id 低4位 R；stock 驱动新消息走 `rpmsg-rx`(ch0)。R=0 使新消息发 ch0 命中 stock，Linux 零改。固件与 dts `rockchip,link-id` 须同步 0x10。

## rt-thread 差异（订正「BSP 默认满足」误判）

- link-id **须 app 自写 0x10**：厂商 `rpmsg_test.c` 用 `0x03`(R=3) 卡 link-up，弃用；`rk3568_amp_rtt_demo` 自写 echo。
- **222 须 app 补进 AMP GIC 白名单（根因）**：gicInit=0 下 `HAL_GIC_Enable(222)` 被 `GIC_AmpCheckIrqValid` 门控，仅 `HAL_GIC_Init` 经 `irqsCfg` 进 `ampValid` 的 IRQ 可使能，BSP 仅 `COMMON_TEST` flag 下含 222。app 在 rpmsg init 前再调一次 `HAL_GIC_Init`（只含 222、`cpuAff` 非本核）补白名单。约束2 由 BSP 默认满足。

## 易踩坑

link-id 两侧不同步 → 握手崩；接收恒走 A2B ch3（物理 cpu_id）与 link-id 无关；辨症：`MBOX0 A2B_STATUS ch3` 起不消费=222 未使能（devmem 可读）。
