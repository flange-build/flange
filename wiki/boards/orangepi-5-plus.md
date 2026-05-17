---
title: orangepi-5-plus
type: board
status: wip
sources:
  - components/board/orangepi-5-plus/config.py
  - components/board/orangepi-5-plus/overlay/etc/hostname
  - components/board/orangepi-5-plus/overlay/etc/usbdevice.conf
  - components/platform/rockchip/rk3588/config.py
related:
  - "[[radxa-rock5b]]"
  - "[[rockchip 平台]]"
  - "[[out-of-tree 模块]]"
  - "[[新增板级支持]]"
updated: 2026-05-17
---

## TL;DR

OrangePi 5 Plus，RK3588，项目第二块 RK3588 板。首版落地：eMMC + UART2 + SSH + M.2 E-Key RTL8852BE WiFi/BT，逐字段复用 [[radxa-rock5b]] 模板。HDMI / NPU / NVMe / 板载 AP6275P / 双 2.5G NIC 显式配置 / PWM 风扇 / RGB LED 不在范围（RTL8125 走 r8169 主线驱动零配置自动 probe）。

## product / variant

```
lunch orangepi-5-plus-default-debug
lunch orangepi-5-plus-default-release
```

## 与 ROCK 5B 差异

| 项 | 值 |
|---|---|
| DTB | `rk3588-orangepi-5-plus`（rkr5.1 已含） |
| hostname | `orangepi-5-plus` |
| 板私有 dtso | 不携带（SoC 已切 mainline panthor，emergency rollback overlay 第二板不再背） |

其余（u-boot 仓 + `next-dev-v2026.01` + generic `rk3588_defconfig`、kernel `linux-6.1-stan-rkr5.1` + panthor fragment、mali-csf firmware、rockchip-mpp 多媒体栈、5 分区布局、RTL8852BE OOT 链路、UART2 1500000 console、mkimage_chip=rk3588）沿用 SoC 层与 ROCK 5B。

## WiFi / BT

逐字段等价 [[radxa-rock5b]]：rkwifibt OOT 编 `8852be.ko`，BT 走 in-tree btusb + 板私有 firmware 拷 `rtl8852bu_fw.bin` / `rtl8852bu_config.bin` 到 `/lib/firmware/rtl_bt/`。
