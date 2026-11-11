# orangepi-cm5-tablet

> 阅读前提：先完成[初学指南](../first-steps.md)的环境准备，运行
> `flange target list orangepi-cm5-tablet` 确认当前目标，再按该型号硬件说明匹配介质、接口与下载模式。
> 本页是配置摘要与硬件记录；下文验收只覆盖记录的版本、产品和测试项，不代表当前全部组合已实测。
> [返回板卡索引](README.md) · [构建与刷写流程](../development-guide.md)

## 概述

OrangePi CM5 Tablet，RK3588S，项目首块原生 RK3588S 实板（此前仅 [radxa-rock5c-lite](radxa-rock5c-lite.md) 通过 RK3582 共享 dts 覆盖）。首版落地：eMMC + UART2 + SSH + 板载 AP6256 WiFi/BT。Tablet 形态特有外设（DSI LCD / 触屏 / 电池 PMIC / MIPI CSI 相机）一律不在范围。

## product / variant

提供 `default/desktop`，均支持 `debug/release`。

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
| usbmode/gadget.d/ | 不携带（与 cm4 / rock5c-lite 对齐） |
| kernel patches | 仅 `0001` bcmdhd FW_AMPAK_PATH（cm4 0002 逐字节复用） |
| extra_firmware | radxa-firmware 仓拉 AP6256 三件套到 `/lib/firmware/brcm/`（与 cm4 同源） |
| bootloader | SoC 层 generic `rk3588_defconfig`，首版无板级覆盖 |

## AP6256 WiFi/BT 链路

驱动栈走 in-tree Rockchip bcmdhd（`drivers/net/wireless/rockchip_wlan/rkwifi/bcmdhd/`），与 [orangepi-cm4](orangepi-cm4.md) **完全同源**：

- WiFi：SDIO 接 Rockchip bcmdhd（CONFIG_BCMDHD=y/m 通过 Kconfig `default y` 链由 SoC 层 `rockchip_linux_defconfig` 启用），固件由 driver 按 chip-id 拼名 `fw_bcm43456c5_ag.bin` 加载
- BT：UART 接 in-tree btbcm，固件 `BCM4345C5.hcd` 由 patchram 上传

固件部署 + 路径约束：

- `rootfs.extra_firmware` 三件套（同 cm4）→ `/lib/firmware/brcm/`
- patch `0001-bcmdhd-set-fw-ampak-path-brcm.patch` 启用 `-DFW_AMPAK_PATH="\"brcm\""`，让 driver 按 `/lib/firmware/brcm/<file>` 查找——这是 in-tree bcmdhd 与 firmware 部署路径对齐的硬约束（不带 patch → driver 查 `/lib/firmware/<file>` → 找不到 → WiFi 不起来）

## 板级补丁边界

| cm4 patch | cm5-tablet 是否携带 | 原因 |
|---|---|---|
| `0001` dtsi bootargs fix | ✗ | 路径写死 `rk3566-orangepi-cm4.dtsi`，cm5-tablet 用 RK3588S dts 路径不通用；如复现 root=PARTUUID 覆盖 extlinux 问题，另写 patch |
| `0002` bcmdhd FW_AMPAK_PATH | ✓ | in-tree bcmdhd Makefile 修改，与 board 无关，AP6256 板必备 |
| NPU 供电补丁 | 不照搬 | CM4 的 RK3566 / RK809 供电路径不同，不能用于推断 RK3588S 的 NPU 可用性 |

## 当前未覆盖的功能

- 不点亮 DSI LCD（`-tablet-lcd.dtsi` 已含但不引入对应 panel driver / backlight）
- 不配置触屏 / 电池 / 充电 PMIC / G-sensor / 板载相机
- 不支持 NVMe / SATA / SD 启动（仅 eMMC）
- 不验证 HDMI / GPU 图形栈 / VPU

共享配置与启动机制见 [Rockchip 平台](../platforms/rockchip.md)。
