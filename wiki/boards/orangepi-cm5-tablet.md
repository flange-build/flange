---
title: orangepi-cm5-tablet
type: board
status: wip
sources:
  - components/board/orangepi-cm5-tablet/config.jsonnet
  - components/board/orangepi-cm5-tablet/overlay/etc/hostname
  - components/board/orangepi-cm5-tablet/patches/kernel/0001-bcmdhd-set-fw-ampak-path-brcm.patch
  - components/platform/rockchip/rk3588s/config.jsonnet
  - docs/first-steps.md
related:
  - "[[orangepi-cm4]]"
  - "[[orangepi-5-plus]]"
  - "[[radxa-rock5c-lite]]"
  - "[[rockchip 平台]]"
  - "[[新增板级支持]]"
updated: 2026-09-05
---

> 阅读前提：先完成[初学指南](../../docs/first-steps.md)的环境准备，运行
> `flange target list orangepi-cm5-tablet` 确认当前目标，再按该型号硬件说明匹配介质、接口与下载模式。
> 本页是配置摘要与硬件记录；下文验收只覆盖记录的版本、产品和测试项，不代表当前全部组合已实测。
> [返回板卡索引](index.md) · [构建与刷写流程](../workflows/lunch-build-flash-流程.md)

## TL;DR

OrangePi CM5 Tablet，RK3588S，项目首块原生 RK3588S 实板（此前仅 [[radxa-rock5c-lite]] 通过 RK3582 共享 dts 覆盖）。首版落地：eMMC + UART2 + SSH + 板载 AP6256 WiFi/BT。Tablet 形态特有外设（DSI LCD / 触屏 / 电池 PMIC / MIPI CSI 相机）一律不在范围。

## product / variant

```
lunch orangepi-cm5-tablet-default-debug
lunch orangepi-cm5-tablet-default-release
```

## 关键差异点

| 项 | 值 |
|---|---|
| SoC | RK3588S（与 RK3588 同 die，少 PCIe / 显示通道 / USB 接口） |
| DTB | `rk3588s-orangepi-cm5-tablet`（rkr5.1 已含；含 `-tablet-lcd.dtsi` + 3 个 `-tablet-camera*.dtsi`，首版均不启用） |
| hostname | `orangepi-cm5-tablet` |
| board overlay | 不携带 `dtso/`、不携带 `boot.overlays.board` |
| usbdevice.conf | 不携带（与 cm4 / rock5c-lite 对齐） |
| kernel patches | 仅 `0001` bcmdhd FW_AMPAK_PATH（cm4 0002 逐字节复用） |
| extra_firmware | radxa-firmware 仓拉 AP6256 三件套到 `/lib/firmware/brcm/`（与 cm4 同源） |
| bootloader | SoC 层 generic `rk3588_defconfig`，首版无板级覆盖 |

## AP6256 WiFi/BT 链路

驱动栈走 in-tree Rockchip bcmdhd（`drivers/net/wireless/rockchip_wlan/rkwifi/bcmdhd/`），与 [[orangepi-cm4]] **完全同源**：

- WiFi：SDIO 接 Rockchip bcmdhd（CONFIG_BCMDHD=y/m 通过 Kconfig `default y` 链由 SoC 层 `rockchip_linux_defconfig` 启用），固件由 driver 按 chip-id 拼名 `fw_bcm43456c5_ag.bin` 加载
- BT：UART 接 in-tree btbcm，固件 `BCM4345C5.hcd` 由 patchram 上传

固件部署 + 路径约束：

- `rootfs.extra_firmware` 三件套（同 cm4）→ `/lib/firmware/brcm/`
- patch `0001-bcmdhd-set-fw-ampak-path-brcm.patch` 启用 `-DFW_AMPAK_PATH="\"brcm\""`，让 driver 按 `/lib/firmware/brcm/<file>` 查找——这是 in-tree bcmdhd 与 firmware 部署路径对齐的硬约束（不带 patch → driver 查 `/lib/firmware/<file>` → 找不到 → WiFi 不起来）

## 不携带的 cm4 patch

| cm4 patch | cm5-tablet 是否携带 | 原因 |
|---|---|---|
| `0001` dtsi bootargs fix | ✗ | 路径写死 `rk3566-orangepi-cm4.dtsi`，cm5-tablet 用 RK3588S dts 路径不通用；如复现 root=PARTUUID 覆盖 extlinux 问题，另写 patch |
| `0002` bcmdhd FW_AMPAK_PATH | ✓ | in-tree bcmdhd Makefile 修改，与 board 无关，AP6256 板必备 |
| `0003` disable rknpu | ✗ | cm5-tablet dts 上 NPU 状态未验；apply 阶段 dmesg 复现 `panic_on_set_idle` 后另起 change |

## 首版 Non-Goals

- 不点亮 DSI LCD（`-tablet-lcd.dtsi` 已含但不引入对应 panel driver / backlight）
- 不配置触屏 / 电池 / 充电 PMIC / G-sensor / 板载相机
- 不支持 NVMe / SATA / SD 启动（仅 eMMC）
- 不验证 HDMI / GPU 图形栈 / VPU

参见 change `add-rk3588s-orangepi-cm5-tablet` 的 proposal.md / design.md / specs/ 获取完整契约与决策路径。
