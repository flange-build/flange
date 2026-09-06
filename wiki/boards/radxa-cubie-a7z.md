---
title: radxa-cubie-a7z
type: board
status: wip
sources:
  - components/board/radxa-cubie-a7z/config.jsonnet
  - components/board/radxa-cubie-a7z/dtso/sun60iw2p1-spi1-st7789v-display.dtso
  - components/board/radxa-cubie-a7z/firmware/panel/st7789v2-240x280.txt
  - components/board/radxa-cubie-a7z/overlay/etc/usbdevice.conf
  - components/board/radxa-cubie-a7z/overlay/etc/modules-load.d/aic8800.conf
  - components/board/radxa-cubie-a7z/overlay/etc/modprobe.d/aic8800.conf
  - docs/first-steps.md
  - components/platform/allwinnera733/patches/kernel/01-tinydrm-panel-mipi-dbi.patch
  - docs/proposal/fb-gpu-test/fb-gpu-test.md
related:
  - "[[allwinnera733 平台]]"
  - "[[lunch-build-flash 流程]]"
  - "[[新增板级支持]]"
  - "[[out-of-tree 模块]]"
updated: 2026-09-05
---

> 阅读前提：先完成[初学指南](../../docs/first-steps.md)的环境准备，运行
> `flange target list radxa-cubie-a7z` 确认当前目标，再按该型号硬件说明匹配介质、接口与下载模式。
> 本页是配置摘要与硬件记录；下文验收只覆盖记录的版本、产品和测试项，不代表当前全部组合已实测。
> [返回板卡索引](index.md) · [构建与刷写流程](../workflows/lunch-build-flash-流程.md)

## TL;DR

Radxa Cubie A7Z，Allwinner A733 SoC，A733 平台首块落地板。已集成 ST7789V SPI LCD、AIC8800 Wi-Fi、PowerVR GPU 驱动、CedarC VE 硬解，刷写工具为 `dd`。

## product / variant

继承 allwinnera733 平台默认：`products: [default]`，`variants: [debug, release]`。

```
lunch radxa-cubie-a7z-default-debug
lunch radxa-cubie-a7z-default-release
```

## 关键差异点

| 项 | 值 |
|---|---|
| DTB | `sun60i-a733-cubie-a7z` |
| kernel_device.board_dts_path | `configs/cubie_a7z/linux-5.15/board.dts` |
| bootloader target | `radxa-cubie-a7z` |
| root 密码 | `1234` |
| 刷写工具 | `dd`（平台层定义） |

A733 平台额外使用 `kernel_device.board_dts_path` 指定 BSP 设备树源文件；所有平台的最终 DTB target 都统一由 `kernel.device_tree.{directory,name}` 描述。

## ST7789V2 SPI LCD

通过 board 私有 overlay `sun60iw2p1-spi1-st7789v-display.dtso` 绑定 mainline `panel-mipi-dbi-spi`（v5.18 → 5.15.147 backport，见 [`01-tinydrm-panel-mipi-dbi.patch`](../../components/platform/allwinnera733/patches/kernel/01-tinydrm-panel-mipi-dbi.patch)），LCD 暴露为 `/dev/dri/card*`。SPI1 引脚：MOSI=PD11, SCLK=PD12, CS=PB3(软CS), DC=PB5, RST=PB6, BLK=PB4(常 3.3V)。Init 序列由 [`firmware/panel/st7789v2-240x280.txt`](../../components/board/radxa-cubie-a7z/firmware/panel/st7789v2-240x280.txt) 经 `builder.firmware_panel` 编码为 `/lib/firmware/panel-mipi-dbi-spi.bin`。280 行圆角模块 (0,20) GRAM 偏移通过 `panel-timing.vback-porch=20` 表达。LCD 不再当系统主控制台。

## AIC8800 USB Wi-Fi

`wifi.aic8800_usb: True`，firmware 从 Radxa aic8800 仓库拉取，安装到 `lib/firmware/aic8800_fw/USB/`（平铺 + aic8800D80 子目录双份）。内核 defconfig 含 `aic8800_wlan.config`。

## GPU

IMG PowerVR BXM-4-64，`pvrsrvkm.ko` 走 [[out-of-tree 模块]] 编译；userspace 驱动 `xserver-xorg-img-bxm` 通过 SoC 层 `rootfs.+extra_debs` 声明（GitHub release + sha256 锁定，构建时直下 + `dpkg -i`）。PoC 见 [docs/proposal/fb-gpu-test/](../../docs/proposal/fb-gpu-test/fb-gpu-test.md)。

## VPU

CedarC VE 硬件解码：内核 `sunxi-ve` 自动 probe（DT compatible），用户态走 `libcedarc-dev v2.0`（SoC 层 `+extra_debs`），覆盖 H.264/H.265/VP9/VP8/MPEG2/MPEG4/MJPEG/AVS/AVS2 与 OMX 组件。

## Device Tree Overlays

vendor overlay 位于 `boot.overlays.vendor`，ST7789V2 板私有 overlay 位于 `boot.overlays.board`；默认项统一放入 `boot.overlays.enabled`。其余可在运行时编辑 `extlinux.conf` 启用。

## overlay

`overlay/etc/usbdevice.conf`（ADB）、`overlay/etc/modules-load.d/aic8800.conf`、`overlay/etc/modprobe.d/aic8800.conf`。fbtft 阶段的 `console-setup` / `st7789v.conf` modules-load 已随 panel-mipi-dbi-spi 切换移除。
