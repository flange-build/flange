---
title: orangepi-cm4
type: board
status: stable
sources:
  - components/board/orangepi-cm4/config.py
  - components/board/orangepi-cm4/overlay/etc/hostname
  - components/board/orangepi-cm4/overlay/etc/usbdevice.conf
related:
  - "[[rockchip 平台]]"
  - "[[lunch-build-flash 流程]]"
  - "[[新增板级支持]]"
updated: 2026-04-26
---

## TL;DR

Orange Pi CM4，RK3566 计算模块，接口丰富（MIPI DSI/CSI、PCIe、HDMI），配置极简，完全依赖平台默认。

## product / variant

继承平台默认：`products: [default]`，`variants: [debug, release]`。

```
lunch orangepi-cm4-default-debug
lunch orangepi-cm4-default-release
```

## 关键差异点

| 项 | 值 |
|---|---|
| DTB | `rk3566-orangepi-cm4-base` |
| kernel patches | 无 |
| bootloader | 使用平台/SoC 默认 commit |

board 层 config.py 仅声明 DTB，其余全部继承上层，是配置最简洁的板子。

## overlay

`overlay/etc/hostname` + `overlay/etc/usbdevice.conf`，无额外定制内容。
