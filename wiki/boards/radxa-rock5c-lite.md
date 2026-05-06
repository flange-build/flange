---
title: radxa-rock5c-lite
type: board
status: wip
sources:
  - components/board/radxa-rock5c-lite/config.py
  - components/board/radxa-rock5c-lite/dtso/rk3588s-rock-5c-otg-peripheral.dtso
  - components/board/radxa-rock5c-lite/dtso/rk3588s-rock-5c-st7789vm-lcd-keys.dtso
  - components/board/radxa-rock5c-lite/firmware/panel/st7789vm-240x240.txt
  - components/board/radxa-rock5c-lite/overlay/etc/hostname
  - components/board/radxa-rock5c-lite/overlay/etc/usbdevice.conf
related:
  - "[[rockchip 平台]]"
  - "[[lunch-build-flash 流程]]"
  - "[[新增板级支持]]"
updated: 2026-05-07
---

## TL;DR

RK3582（binned RK3588，GPU fuse 禁，NPU/VPU/RGA/ISP 保留），共用 `rk3588s-rock-5c` BSP。集成 AIC8800D80 USB Wi-Fi/BT、USB-C OTG peripheral、Waveshare 1.3" ST7789VM LCD HAT（7 键）。

## 关键差异点

| 项 | 值 |
|---|---|
| DTB | `rk3588s-rock-5c`（GPU/A76 fail-soft） |
| kernel | `linux-6.1-stan-rkr5.1` + `rockchip_linux_defconfig` + fragments |
| U-Boot | v2024.10，`rk3588_defconfig`，同一 BootROM |
| console | `ttyS2,1500000` |

## WiFi/BT

AIC8800D80 USB combo（BT+WiFi 6），OOT `7f42b22`（与 cubie-a7z 锁同版）。模块：`aic_load_fw.ko` / `aic8800_fdrv.ko`（私有 stack）/ `aic_btusb.ko`；BT 加 `-Wno-error`。Firmware → `/lib/firmware/aic8800D80/`。

## USB-C OTG

原始 dts `dr_mode="host"` 致 gadget 不可用。`rk3588s-rock-5c-otg-peripheral.dtso` 覆写为 `"peripheral"`，已加入 `default_overlays`。

## 1.3" LCD HAT（ST7789VM 240×240）

RPi 40-pin 堆叠，mainline `panel-mipi-dbi-spi`，SPI4_M2 硬件 CS，init 序列来自 `st7789vm-240x240.txt`，7 路 gpio-keys。

**Pin 占用**：

| HAT 信号 | pin | RK GPIO | 复用 |
|---|---|---|---|
| MOSI/MISO/SCLK/CS0 | 19/21/23/24 | GPIO1_A1/A0/A2/A3 | SPI4_M2 |
| DC/RST | 22/13 | GPIO1_B5/GPIO4_B2 | GPIO out（RST 必 ACTIVE_HIGH） |
| BL | 18 | GPIO1_B0 | 不接管，R2 上拉常亮 |
| K1/K2/K3 | 40/38/36 | GPIO4_B1/A5/A2 | GPIO in+pull_up |
| Joy UP/DOWN/LEFT/PRESS | 31/35/29/33 | GPIO1_B1/GPIO4_A0/GPIO1_B2/GPIO1_B4 | GPIO in+pull_up |
| ~~Joy RIGHT~~ | ~~37~~ | ~~SARADC_VIN2~~ | ❌ 无 GPIO mux |

**易踩坑**：

- **背光不可调光**：GPIO1_B0 所有 mux 均无 PWM，R2 上拉常亮，backlight sysfs 无效。
- **摇杆右键不可用**：pin 37 = SARADC_VIN2，无 GPIO mux，已从 overlay 删除。
- **RST 必须 ACTIVE_HIGH**：`mipi_dbi_hw_reset()` 直写（deassert=拉高）；声明 ACTIVE_LOW 则 panel 永停 reset 无法出图。

## Overlays

均加入 `default_overlays`：`rk3588s-rock-5c-otg-peripheral.dtbo`（OTG peripheral）、`rk3588s-rock-5c-st7789vm-lcd-keys.dtbo`（LCD+键）。`overlay/etc/hostname`=`radxa-rock5c-lite`，`overlay/etc/usbdevice.conf`（ADB）。
