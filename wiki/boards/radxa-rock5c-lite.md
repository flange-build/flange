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

Radxa ROCK 5C Lite，Rockchip RK3582 SoC（binned RK3588 die — 2×A76 + 4×A55，GPU 在 silicon fuse 阶段被禁用，NPU/VPU/RGA/ISP 保留）。与 Rock 5C 共用 PCB 与 BSP dts；已集成 Waveshare 1.3" LCD HAT（ST7789VM drm/tiny + 7 键）、AIC8800D80 USB combo Wi-Fi/BT、USB-C OTG peripheral 模式。

## product / variant

继承 rockchip 平台默认：`products: [default]`，`variants: [debug, release]`。

```
lunch radxa-rock5c-lite-default-debug
lunch radxa-rock5c-lite-default-release
```

## 关键差异点

| 项 | 值 |
|---|---|
| DTB | `rk3588s-rock-5c`（与 RK3588S 板共用；RK3582 fuse 锁定的 GPU/A76 节点 probe fail-soft） |
| kernel branch | `linux-6.1-stan-rkr5.1` |
| kernel defconfig | `rockchip_linux_defconfig` + `case_insensitive_fix.config` + `panel_mipi_dbi.config` |
| bootloader target | `rk3588_defconfig`（generic；RK3582 与 RK3588/S 共 BootROM，u-boot 阶段 fuse 不敏感） |
| console | `ttyS2,1500000` |
| 刷写工具 | `rkdeveloptool`（平台层定义） |

## 启动链路

U-Boot v2024.10 + rkbin（`mkimage_chip = rk3588`）+ 内核 `linux-6.1-stan-rkr5.1`。bootloader 走 SoC 层统一 `rk3588_defconfig`；RK3582 与 RK3588S 同一 BootROM，u-boot 与 SPL 层无需区分 fuse。内核启动后 GPU / 大核 cluster 节点 probe 报 `EPROBE_DEFER` 或 `ENODEV`，属预期 fail-soft，不影响 userspace。

## WiFi/BT — AIC8800D80 USB combo

板载 AIC8800D80 USB combo 卡（USB1.1 host 接口，BT4.2/5.x + WiFi 6 共用 USB endpoint）。驱动走 radxa-pkg/aic8800 OOT 仓库（commit `7f42b22`），与 cubie-a7z 锁同一 commit 以保证 firmware/driver 行为同步（该版本已在 cubie-a7z 实测可用）。

三个 OOT 模块：`aic_load_fw.ko`（firmware bootstrap loader）、`aic8800_fdrv.ko`（Wi-Fi vendor full driver，私有 wireless stack，不走 mac80211/cfg80211）、`aic_btusb.ko`（BT vendor driver，自带 HCI，不走 in-tree btusb）。BT 子树编译时加 `KCFLAGS=-Wno-error`，原因：vendor BT 代码历史包袱重，rkr5.1 内核默认 `-Werror` 会将 unused-variable 等警告升为 fatal。

Firmware 部署到 `/lib/firmware/aic8800D80/`（driver 查找路径为 firmware root + `aic8800D80/<file>`，与 a733 BSP 的 `aic8800_fw/USB/` 风格不同）。

## USB-C OTG

`rk3588s-rock-5c.dts` 原始 dts 将 `&usbdrd_dwc3_0` 的 `dr_mode` 钉成 `"host"`，dwc3 不暴露 UDC，gadget（adbd / FunctionFS）无法 bind。board overlay [`rk3588s-rock-5c-otg-peripheral.dtso`](../../components/board/radxa-rock5c-lite/dtso/rk3588s-rock-5c-otg-peripheral.dtso) 将 `dr_mode` 覆写为 `"peripheral"`，恢复 OTG device 角色。该 overlay 已加入 `default_overlays`，lunch target 镜像默认走 device 模式，方便 adbd / 镜像更新流程。

## 1.3" LCD HAT（ST7789VM 240×240）

Waveshare 1.3" IPS LCD HAT，通过 RPi 40-pin GPIO header 直接堆叠，含 3 个按键 + 5 向摇杆。

**驱动**：mainline drm/tiny `panel-mipi-dbi-spi`，LCD 暴露为 `/dev/dri/card*`，分辨率 240×240，默认横屏（MADCTL=0x70）。Init 序列由 [`firmware/panel/st7789vm-240x240.txt`](../../components/board/radxa-rock5c-lite/firmware/panel/st7789vm-240x240.txt) 经 `builder.firmware_panel` 编码为 `/lib/firmware/panel-mipi-dbi-spi.bin`。SPI 走 SPI4_M2 硬件 CS（片选无需 GPIO bit-bang，时序更稳定）。

**按键**：7 路 gpio-keys，K1/K2/K3 → `KEY_F1`/`KEY_F2`/`KEY_F3`；Joy UP/DOWN/LEFT/PRESS → 方向键 + `KEY_ENTER`，标准 evdev 输入设备。

**Pin 占用**：

| HAT 信号 | 物理 pin | RK GPIO | 复用 |
|---|---|---|---|
| MOSI / MISO / SCLK / CS0 | 19 / 21 / 23 / 24 | GPIO1_A1 / A0 / A2 / A3 | SPI4_M2（硬件 CS） |
| DC / RST | 22 / 13 | GPIO1_B5 / GPIO4_B2 | GPIO output（RST 必 ACTIVE_HIGH） |
| BL | 18 | GPIO1_B0 | **不接管**：硬件 R2=10K 上拉默认常亮 |
| K1 / K2 / K3 | 40 / 38 / 36 | GPIO4_B1 / A5 / A2 | GPIO input + pull_up |
| Joy UP / DOWN / LEFT / PRESS | 31 / 35 / 29 / 33 | GPIO1_B1 / GPIO4_A0 / GPIO1_B2 / GPIO1_B4 | GPIO input + pull_up |
| ~~Joy RIGHT~~ | ~~37~~ | ~~SARADC_VIN2~~ | ❌ 物理上无 GPIO mux，不可用 |

**启用方式**：overlay [`rk3588s-rock-5c-st7789vm-lcd-keys.dtso`](../../components/board/radxa-rock5c-lite/dtso/rk3588s-rock-5c-st7789vm-lcd-keys.dtso) 已加入 `default_overlays`，开机即生效，无需手工启用。

**易踩坑**：

- **背光不可调光**：pin 18 (GPIO1_B0) 七个 mux function 均无 PWM；dts 未声明 backlight 节点，写 `/sys/class/backlight/*/brightness` 无效；硬件 R2=10K 上拉常亮，背光为固定亮度。
- **摇杆右键不可用**：HAT 原理图 BCM26 落到 pin 37 = SARADC_VIN2，该 pin 无 GPIO mux（仅模拟输入），无法作为 gpio-keys 节点，已从 overlay 中删除。
- **RST GPIO 极性**：DT 必须声明 `GPIO_ACTIVE_HIGH`（非默认的 `ACTIVE_LOW`）。mainline `mipi_dbi_hw_reset()` 按直写语义操作 gpio（deassert = 拉高），若声明为 ACTIVE_LOW 则 reset 永远有效，panel 永停 reset 态无法出图。详见 dtso 文件头注释。

## Device Tree Overlays

2 个 board overlay，均已加入 `default_overlays`，开机自动应用：

| overlay | 作用 |
|---|---|
| `rk3588s-rock-5c-otg-peripheral.dtbo` | USB-C OTG 切 peripheral（恢复 adbd / gadget） |
| `rk3588s-rock-5c-st7789vm-lcd-keys.dtbo` | ST7789VM LCD + 7 键 gpio-keys |

## overlay

`overlay/etc/hostname`（板名 `radxa-rock5c-lite`）、`overlay/etc/usbdevice.conf`（ADB USB device 配置）。
