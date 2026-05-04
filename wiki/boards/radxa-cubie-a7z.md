---
title: radxa-cubie-a7z
type: board
status: wip
sources:
  - components/board/radxa-cubie-a7z/config.py
  - components/board/radxa-cubie-a7z/overlays/sun60iw2p1-spi1-st7789v-display.dtso
  - components/board/radxa-cubie-a7z/firmware/panel/st7789v2-240x280.txt
  - components/board/radxa-cubie-a7z/overlay/etc/usbdevice.conf
  - components/board/radxa-cubie-a7z/overlay/etc/modules-load.d/aic8800.conf
  - components/board/radxa-cubie-a7z/overlay/etc/modprobe.d/aic8800.conf
related:
  - "[[allwinnera733 平台]]"
  - "[[lunch-build-flash 流程]]"
  - "[[新增板级支持]]"
  - "[[out-of-tree 模块]]"
updated: 2026-05-04
---

## TL;DR

Radxa Cubie A7Z，Allwinner A733 SoC，A733 平台首块落地板。已集成 ST7789V SPI LCD、AIC8800 Wi-Fi、PowerVR GPU 驱动，刷写工具为 `dd`。

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

A733 平台使用 `kernel_device.board_dts_path` 指定设备树源文件路径，与 Rockchip 平台使用 `kernel.dts` 直接引用 DTB target 的机制不同。

## ST7789V2 SPI LCD

通过 board 私有 overlay `sun60iw2p1-spi1-st7789v-display.dtso` 绑定 mainline `panel-mipi-dbi-spi`（v5.18 → 5.15.147 backport，见 [`01-tinydrm-panel-mipi-dbi.patch`](../../components/platform/allwinnera733/patches/kernel/01-tinydrm-panel-mipi-dbi.patch)），LCD 暴露为 `/dev/dri/card*`。SPI1 引脚：MOSI=PD11, SCLK=PD12, CS=PB3(软CS), DC=PB5, RST=PB6, BLK=PB4(常 3.3V)。Init 序列由 [`firmware/panel/st7789v2-240x280.txt`](../../components/board/radxa-cubie-a7z/firmware/panel/st7789v2-240x280.txt) 经 `builder.firmware_panel` 编码为 `/lib/firmware/panel-mipi-dbi-spi.bin`。280 行圆角模块 (0,20) GRAM 偏移通过 `panel-timing.vback-porch=20` 表达。LCD 不再当系统主控制台。

## AIC8800 USB Wi-Fi

`wifi.aic8800_usb: True`，firmware 从 Radxa aic8800 仓库拉取，安装到 `lib/firmware/aic8800_fw/USB/`（平铺 + aic8800D80 子目录双份）。内核 defconfig 含 `aic8800_wlan.config`。

## GPU

IMG PowerVR BXM-4-64，`pvrsrvkm.ko` 走 [[out-of-tree 模块]] 编译；userspace 驱动 `xserver-xorg-img-bxm` 通过 SoC 层 `rootfs.+extra_debs` 声明（GitHub release + sha256 锁定，构建时直下 + `dpkg -i`）。PoC 见 [docs/proposal/fb-gpu-test/](../../docs/proposal/fb-gpu-test/fb-gpu-test.md)。

## Device Tree Overlays

28 个 vendor overlay（`boot.vendor_overlays`）+ 1 个 board overlay（ST7789V2 LCD，`boot.board_overlays`）。仅 ST7789V2 overlay 默认启用（`boot.default_overlays`）。其余运行时编辑 `extlinux.conf` 启用。

## overlay

`overlay/etc/usbdevice.conf`（ADB）、`overlay/etc/modules-load.d/aic8800.conf`、`overlay/etc/modprobe.d/aic8800.conf`。fbtft 阶段的 `console-setup` / `st7789v.conf` modules-load 已随 panel-mipi-dbi-spi 切换移除。
