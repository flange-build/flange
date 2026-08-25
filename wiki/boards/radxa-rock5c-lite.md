---
title: radxa-rock5c-lite
type: board
status: wip
sources:
  - components/board/radxa-rock5c-lite/config.jsonnet
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

原始 dts `dr_mode="host"` 致 gadget 不可用。`rk3588s-rock-5c-otg-peripheral.dtso` 覆写为 `"peripheral"`，已加入 `boot.overlays.enabled`。

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
- **init seq 必须用 ST7789VM 参数**：cubie-a7z 那份 ST7789V2 init 不通用（gamma/VCOMS/GCTRL 不同）；用 V2 参数会导致**下面 1/3 行花屏**。本板 firmware 已照 Waveshare 官方 LCD_1in3 demo 校好，commit `367f9be`。

**用户态出图**：

```bash
# 一次性：解 fbcon (raw fb 写入不会触发 SPI flush；fbcon 也会抢屏)
echo 0 > /sys/class/vtconsole/vtcon1/bind

# modetest（最简，一帧静态图）
modetest -M panel-mipi-dbi -s 31@34:240x240 -F smpte
```

```bash
# GStreamer (videotestsrc / mpp 解码 / v4l2 摄像头通用)
gst-launch-1.0 videotestsrc pattern=ball ! videoconvert ! \
  video/x-raw,width=240,height=240,format=BGRx,framerate=10/1 ! \
  kmssink driver-name=panel-mipi-dbi connector-id=31 plane-id=32 \
  force-modesetting=true sync=false
```

GStreamer 这条管线 6 个参数缺一不可：

- `driver-name=panel-mipi-dbi`：不指会枚举到 card0 (HDMI)
- `connector-id` / `plane-id`：用 `modetest -M panel-mipi-dbi -p` 查
- `force-modesetting=true`：让 kmssink 真去 setCRTC
- `sync=false`：drm/tiny `async page flip (✗)`，开 sync 卡死
- `format=BGRx`（DRM XR24）：**不要用 RGB16**，kmssink RG16 路径在 drm/tiny 上有 bug 出黑屏；XR24 由 driver 自动转 RG16 给 SPI
- 帧率 ≤15fps：SPI 40MHz × 240×240×2B 实测上限 ~28fps（modetest -v 报）

## Overlays

均加入 `boot.overlays.enabled`：`rk3588s-rock-5c-otg-peripheral.dtbo`（OTG peripheral）、`rk3588s-rock-5c-st7789vm-lcd-keys.dtbo`（LCD+键）。`overlay/etc/hostname`=`radxa-rock5c-lite`，`overlay/etc/usbdevice.conf`（ADB）。
