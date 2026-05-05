---
title: radxa-rock5b
type: board
status: wip
sources:
  - components/board/radxa-rock5b/config.py
  - components/board/radxa-rock5b/overlay/etc/hostname
  - components/board/radxa-rock5b/overlay/etc/usbdevice.conf
  - components/platform/rockchip/rk3588/config.py
related:
  - "[[rockchip 平台]]"
  - "[[lunch-build-flash 流程]]"
  - "[[新增板级支持]]"
updated: 2026-05-05
---

## TL;DR

Radxa ROCK 5B，RK3588 SoC（4×A76 + 4×A55），项目首块 RK3588 适配板。首版仅验证 eMMC 启动 + UART2 串口 + GbE/SSH 链路；HDMI / GPU / NPU / VPU / NVMe / Wi-Fi 不在范围。

## product / variant

继承平台默认：`products: [default]`，`variants: [debug, release]`。

```
lunch radxa-rock5b-default-debug
lunch radxa-rock5b-default-release
```

## 关键差异点

| 项 | 值 |
|---|---|
| SoC | RK3588（首颗，与 RK3566 共用 argon BSP rkr4.1-buildroot 分支） |
| DTB | `rk3588-rock-5b` |
| u-boot 分支 | `radxa/u-boot @ next-dev-v2024.10`（RK3566/RK3588 全平台统一） |
| u-boot defconfig | `rk3588_defconfig`（沿用 SoC generic，走 extlinux.conf；不用 board-specific 因其内置 androidboot 风格 bootargs 绕过 extlinux） |
| 调试串口 | UART2，1500000 bps（与 RK3566 一致） |
| mkimage chip | `rk3588`（同 die RK3588S 共用） |
| 分区布局 | 沿用 RK3566 5 分区（idbloader/uboot/boot/recovery/rootfs） |

## overlay

`overlay/etc/hostname`、`overlay/etc/usbdevice.conf`（USB gadget gadget group=rockchip，与 zero3w 同模板）。

## 首版验收

maskrom → 5 分区刷写 → 串口 U-Boot/kernel banner → systemd → eth0 拿 IP → ssh 登录成功。
