---
title: radxa-rock5b
type: board
status: wip
sources:
  - components/board/radxa-rock5b/config.jsonnet
  - components/board/radxa-rock5b/dtso/rk3588-rock-5b-mali-valhall-compat.dtso
  - components/board/radxa-rock5b/overlay/etc/hostname
  - components/board/radxa-rock5b/overlay/etc/usbmode/gadget.d/20-radxa-rock5b.yaml
  - components/board/radxa-rock5b/docs/radxa_rock_5b_v1423_sch.pdf
  - components/packages/meizu-e3-panel/package.py
  - components/packages/meizu-e3-panel/device-tree/rk3588-rock-5b-meizu-e3-panel.dtso
  - components/platform/rockchip/rk3588/config.jsonnet
  - docs/first-steps.md
related:
  - "[[rockchip 平台]]"
  - "[[out-of-tree 模块]]"
  - "[[硬件特性包]]"
  - "[[lunch-build-flash 流程]]"
  - "[[新增板级支持]]"
  - "[[adbd]]"
updated: 2026-09-16
---

> 阅读前提：先完成[初学指南](../../docs/first-steps.md)的环境准备，运行
> `flange target list radxa-rock5b` 确认当前目标，再按该型号硬件说明匹配介质、接口与下载模式。
> 本页是配置摘要与硬件记录；下文验收只覆盖记录的版本、产品和测试项，不代表当前全部组合已实测。
> [返回板卡索引](index.md) · [构建与刷写流程](../workflows/lunch-build-flash-流程.md)

## TL;DR

Radxa ROCK 5B，RK3588 SoC（4×A76 + 4×A55），项目首块 RK3588 适配板。已落地：eMMC 启动 + UART2 串口 + GbE/SSH + GPU（mainline panthor）+ M.2 E-Key RTL8852BE WiFi6/BT + VPU 硬解（mpp / RGA / GStreamer-rockchip）+ USB adb（含 macOS 主机，2026-08-27 验证）。HDMI / NPU / NVMe 不在范围。

## product / variant

板级提供 `default`、`desktop`、`meizu-e3-bringup` 和 `rockmedia`，均支持 `debug/release`。
`rockmedia` 是厂商 GPU 多媒体基座，其余产品使用 Panthor。

```
lunch radxa-rock5b-default-debug
lunch radxa-rock5b-default-release
lunch radxa-rock5b-rockmedia-debug
lunch radxa-rock5b-rockmedia-release
```

选定目标后执行 `flange build`。`rockmedia` 包含 BSP mali_kbase + Mali-G610 g24p0
X11/Wayland/GBM 用户态驱动，以及 MPP、RGA、GStreamer 与 Rockchip 插件；默认不启动图形桌面。
完整说明及实机验收见 [厂商 GPU 多媒体基座](../../components/packages/rockchip-mali-g610/README.md)。
切换 GPU 栈时必须同时更新 boot 和 rootfs；新增产品的硬件表现尚待实机验收。

## 关键差异点

| 项 | 值 |
|---|---|
| SoC | RK3588（首颗，BSP 分支 `linux-6.1-stan-rkr5.1`；rkr4.1-buildroot 的 mali_kbase 在 r0p0 silicon 上 RCU stall，必须 rkr5+） |
| DTB | `rk3588-rock-5b` |
| u-boot 分支 | `radxa/u-boot @ next-dev-v2026.01`（RK3566/RK3588 全平台统一；v2024.10 在 tspi-rk3566 上 USB OTG configfs gadget 不枚举，整平台切到 v2026.01） |
| u-boot defconfig | `rk3588_defconfig`（沿用 SoC generic，走 extlinux.conf；不用 board-specific 因其内置 androidboot 风格 bootargs 绕过 extlinux） |
| GPU | 默认 Panthor；rockmedia 使用 BSP mali_kbase CSF + g24p0 libmali，配套启用板私有 compatible overlay |
| 调试串口 | UART2，1500000 bps（与 RK3566 一致） |
| mkimage chip | `rk3588`（同 die RK3588S 共用） |
| 分区布局 | 沿用 RK3566 5 分区（idbloader/uboot/boot/recovery/rootfs） |

## WiFi / BT

M.2 E-Key 槽位（`pcie2x1l0`，dts 默认 okay，PCIe ID `10ec:b852`）走 RTL8852BE PCIe WiFi6 + USB BT 5.2 combo。in-tree rtw89 不含 8852BE 子驱动（mainline 6.2 才进，rkr5.1 没回移），改走 [[out-of-tree 模块]]：

- `kernel.oot_sources.rkwifibt`：`radxa/rkwifibt @ develop` —— vendor 私有 stack 不依赖 mac80211
- `+oot_modules` 编 `drivers/rtl8852be` → `8852be.ko`（默认 `CONFIG_RTL8852B=y` + `CONFIG_PCI_HCI=y`，无需额外 make 参数）
- BT 走 in-tree btusb（rockchip_linux_defconfig 已 `BT_HCIBTUSB=y` + `BT_HCIBTUSB_RTL=y`）+ `+rootfs.extra_firmware` `source: oot:rkwifibt` 复用同源拷 `rtl8852bu_fw.bin` / `rtl8852bu_config.bin` 到 `/lib/firmware/rtl_bt/`

## VPU / 多媒体加速

板级显式启用 [rockchip-multimedia](../../components/packages/rockchip-multimedia/README.md)，
在 Docker 中自编 MPP 1.3.9、RGA 2.1.0、带 Rockchip 补丁的 GStreamer 1.24.2 及
`gstreamer1.0-rockchip`，重打为本地 DEB。GStreamer element（处理节点）包含 `mppvideodec`、
`mpph264enc`、`mpph265enc` 等。历史板卡记录中的编解码性能不代表新增 rockmedia 组合已验收。

## MIPI-DSI 屏（meizu-e3-panel）

经 [[硬件特性包]] 启用魅族 E3 39pin MIPI-DSI 屏（显示+触摸+背光），`packages: [{name: meizu-e3-panel, drivers: [sec_ts, sgm37604a]}]`。接线按原理图 v1.423：

| 功能 | rock5b 落点 |
|---|---|
| DSI | dsi1（DPHY1 4lane）→ VP3 路由；panel↔dsi1 需 OF-graph port@1/port@0 |
| 触摸 | `sec_ts` OOT @i2c6 0x48；irq gpio0 PD3；TP_RST gpio0 PC6（gpio-hog 解复位） |
| 背光 | `sgm37604a` OOT I2C @i2c6 0x36（**非** 板载 MP3302/pwm-backlight）；使能 gpio0 PA0 |
| 屏复位 | LCD_RESET gpio2 PC1 |
| LCD 供电 | LCD_PWREN_H gpio1 PC4 → GPIO 使能 always-on regulator |

实机已点亮。易踩坑：U-Boot 2017.09 overlay 根节点须包 `fragment`；默认亮度别用极低值（led 4 路+40mA+default 2048）；**sgm37604a 驱动 probe 时机太早（LCD_3V3 刚上电）写 MODE(0x11)/CURRENT(0x1B) 寄存器不生效，芯片停在 0x11=0x65 错误调光模式致背光极暗——驱动改为在 `update_status`（panel 使能后）重写 MODE/LED/CURRENT 才稳**。详见 `openspec/changes/archive/2026-05-21-add-meizu-e3-panel-package/`。

## USB adb（fc000000.usb OTG 口）

2026-08-27 全链路验证通过（macOS 主机）：冷启动零干预 `adb devices` 即现 → root shell；push 85.6 MB/s（USB 2.0 近线速）；TCP 5555 并行；`adb shell` 为 login bash（与 ssh 体验一致）。此前接 macOS 主机 `adb devices` 永远为空——两层根因（usbdevice 守护循环泄漏雪崩 + 旧 vendor adbd 对 macOS adb host ClearFeature(HALT) 引发的 EPIPE 误判为断开）与完整定位过程见 [[adbd]]（commit 0c9b03a2、e13a6ec7）。本板是该问题的定位与验证载体。

## 板私有 overlay

- `dtso/rk3588-rock-5b-mali-valhall-compat.dtso` — rockmedia 默认启用，将 GPU compatible 改为 `arm,mali-valhall` 以匹配 BSP mali_kbase；其他产品不启用
- `overlay/etc/hostname`、`overlay/etc/usbmode/gadget.d/20-radxa-rock5b.yaml`（usbmoded gadget 板级覆盖，group=rockchip，与 zero3w 同模板；只声明与 App 层默认值不同的键，两者**按键合并** —— App 层新增的键自动对本板生效，无需在此跟进，详见 [[USB gadget 子系统（usbmoded）]]）
