---
title: AMP 协处理器与 rpmsg
type: concept
status: stable
sources:
  - components/board/tspi-rk3566/patches/kernel/0003-add-tspi-rk3566-amp-dts.patch
  - components/app/rk3568_amp_demo/src/main.c
  - components/board/tspi-rk3566/config.py
  - components/platform/rockchip/rk3566/config.py
related:
  - "[[amp 构建器]]"
  - "[[tspi-rk3566]]"
  - "[[rockchip 平台]]"
  - "[[U-Boot 启动链]]"
updated: 2026-06-30
---

## TL;DR

tspi-rk3566 amp product 把 cpu3 切到 AArch32 跑裸机 HAL（rpmsg-lite 从核），Linux 跑 3 核当 master，经 rpmsg + mailbox + 共享 vring(0x7c00000) 通信。从核 console=UART4，Linux console 仍 UART2。

## 启动与摘核

- U-Boot `CONFIG_AMP`+`CONFIG_ROCKCHIP_AMP`（board `bootloader.+defconfig:amp`，走配置非 patch）从 `amp` 分区读 FIT、按 `amp-cpus` entry(0x07000000) PSCI 拉起 cpu3，再引导 Linux 到 cpu0。
- amp dts（board patch 0003）`/delete-node/ &cpu3`，Linux 只 online cpu0-2；`&arm_pmu` 先去 cpu3 affinity。

## rpmsg 链路三约束（缺一不通，上板 /dev/rpmsg0 echo 验证）

1. **link-up 邮箱中断**：固件 `wait_for_link_up` 死等本核标志，仅在收到 Linux 首条 mailbox 中断 `MBOX0_CH3_A2B`(INTID 222) 时由 ISR 置位。222 必须进 `&rockchip_amp` 的 `amp-irqs` 路由到 cpu3，否则 Linux `gic_dist_init` 把它改回 cpu0。
2. **不抢 GICD**：固件 `GIC_IRQ_AMP_CTRL.cpuAff` 设非本核（gicInit=0），从核不重初始化 GIC 分发器，否则与 Linux 抢挂死（即"加 amp-irqs 就停打印"的真因）。
3. **反向通道走 link-id（驱动零 fork）**：rpmsg-lite `platform_notify` 发送通道 = link-id 低4位(R)。stock `rockchip_rpmsg_mbox` 期望新消息走 `rpmsg-rx`(ch0)→rx 回调→vq[0]。故 link-id 取 **0x10**(R=0)，固件新消息发 ch0 命中 stock 回调，Linux 驱动一行不改（上游 radxa/rockchip-linux 同）。app `main.c` 与 dts `&rpmsg` 的 `rockchip,link-id` 须同步 0x10。

## 易踩坑

- 三处须原子改；link-id 两侧不同步 → 握手 `env_isr` 命中空槽崩。
- 接收恒走 A2B ch3（物理 cpu_id 决定），与 link-id 无关。
- 早期反向通道曾 patch 内核 `tx_callback` 补 kick vq[0]（patch 0004），已废弃改 link-id。
