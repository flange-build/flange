---
title: radxa-zero3w
type: board
status: stable
sources:
  - components/board/radxa-zero3w/config.jsonnet
  - components/board/radxa-zero3w/overlay/etc/hostname
  - components/board/radxa-zero3w/overlay/etc/usbdevice.conf
related:
  - "[[rockchip 平台]]"
  - "[[lunch-build-flash 流程]]"
  - "[[新增板级支持]]"
updated: 2026-04-26
---

## TL;DR

Radxa Zero 3W，RK3566 SoC，WiFi/BT 板型（802.11ac + BT5），项目首个打样验证目标，构建与刷写流程均已完整跑通。

## product / variant

继承平台默认：`products: [default]`，`variants: [debug, release]`。

lunch 示例：

```
lunch radxa-zero3w-default-debug
lunch radxa-zero3w-default-release
```

## 关键差异点

| 项 | 值 |
|---|---|
| DTB | `rk3566-radxa-zero-3w` |
| kernel patches | 无（使用平台/SoC 默认） |
| board patches | 无 |

## overlay

`overlay/etc/hostname` — 设备主机名；`overlay/etc/usbdevice.conf` — USB gadget 配置（ADB/串口）。其余均走平台默认。
