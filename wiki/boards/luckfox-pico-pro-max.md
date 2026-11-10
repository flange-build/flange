---
title: luckfox-pico-pro-max
type: board
status: stable
sources:
  - components/board/luckfox-pico-pro-max/config.jsonnet
  - components/board/luckfox-pico-pro-max/patches/bootloader/0001-fix-vendor-fit-bootdev.patch
  - components/board/luckfox-pico-pro-max/patches/kernel/0001-add-luckfox-pico-pro-max-dts.patch
  - components/platform/rockchip/rv1106/config.jsonnet
  - openspec/changes/add-rv1106-luckfox-pico-pro-max/verification.md
  - openspec/changes/add-alpine-distro-layer/verification.md
related:
  - "[[rockchip 平台]]"
  - "[[FlashStrategy 抽象]]"
updated: 2026-11-10
---

> 阅读前提：先完成[初学指南](../../docs/first-steps.md)的环境准备，运行
> `flange target list luckfox-pico-pro-max` 确认当前目标，再按该型号硬件说明匹配介质、接口与下载模式。
> 本页是配置摘要与硬件记录；下文验收只覆盖记录的版本、产品和测试项，不代表当前全部组合已实测。
> [返回板卡索引](index.md) · [构建与刷写流程](../workflows/lunch-build-flash-流程.md)

## TL;DR

Luckfox Pico Pro (RV1106G2 128MB) / Max (RV1106G3 256MB) 单板计算机，Cortex-A7 @ 1.1GHz，256MB SPI NAND（Winbond W25N02KV），板载内置百兆以太网 PHY（rk630phy）、USB 2.0 OTG、用户工作指示灯。支持最小 Ubuntu Base 与 Alpine Linux（musl + apk + OpenRC）发行版。全量产物构建、线刷、网络 DHCP、SSH、USB ADB 与 musl App 链路均已在真机上验证通过。

## 配置与产物

| 项 | 值 |
|---|---|
| SoC | Rockchip RV1106（ARMv7 / Cortex-A7，userspace=armhf，kernel/bootloader=arm） |
| 启动介质 | 256MB SPI NAND（2048B page，128KB PEB），GPT 分区表 |
| Bootloader | U-Boot（`rv1106_defconfig` + `rv1106-optee.config`，`CONFIG_EFI_PARTITION: 'y'`） |
| 内核 | Linux 6.1.115+（`rv1106g-luckfox-pico-pro-max.dts`，vendor FIT `boot.img`） |
| 根文件系统 | UBI 卷 `ubi0:rootfs`（mtd3，223MB），Alpine Linux（musl + apk + OpenRC）或 Ubuntu Base |
| 调试通道 | USB gadget（FunctionFS adbd + usbmoded），串口 `ttyFIQ0`，以太网 SSH |

## 实机验收记录

- **启动与控制台**：U-Boot 解析 SPI NAND 上的 GPT 分区表，加载 vendor FIT boot.img；Linux 内核启动，板载工作灯以 heartbeat 双闪指示内核运行。
- **存储**：UBI 驱动正确挂载 223MB rootfs 分区并以 UBIFS 启动系统。
- **以太网**：百兆以太网（内置 FEPHY）自动协商 100Mbps/Full，通过 DHCP 获取网络地址，SSH 服务可用。
- **USB 调试（ADB）**：OpenRC 下 usbmoded 管理 DWC3 peripheral，正确拉起 adbd，实机稳定枚举。
- **App 运行时**：通过 `flange app` 成功构建、部署并运行 C++ / musl / zlib 测试程序（`musl-check`）。
