---
title: radxa-dragon-q8b
type: board
status: wip
sources:
  - components/board/radxa-dragon-q8b/config.jsonnet
  - components/board/radxa-dragon-q8b/patches/kernel/0001-dts-q8b-set-usb-roles.patch
  - components/platform/qualcommsc8280xp/sc8280xp/config.jsonnet
  - components/platform/qualcommsc8280xp/patches/kernel/0001-dwc3-gadget-preserve-pending-requests-on-clear-stall.patch
  - components/platform/qualcommsc8280xp/patches/kernel/0002-net-tc956x-zero-init-irq-domain-info.patch
  - openspec/changes/archive/2026-08-30-add-radxa-dragon-q8b/
  - openspec/changes/archive/2026-08-30-fix-radxa-dragon-q8b-usb-ethernet/
  - docs/first-steps.md
related:
  - "[[qualcommsc8280xp 平台]]"
  - "[[radxa-dragon-q6a]]"
  - "[[FlashStrategy 抽象]]"
updated: 2026-09-05
---

> 阅读前提：先完成[初学指南](../../docs/first-steps.md)的环境准备，运行
> `flange target list radxa-dragon-q8b` 确认当前目标，再按该型号硬件说明匹配介质、接口与下载模式。
> 本页是配置摘要与硬件记录；下文验收只覆盖记录的版本、产品和测试项，不代表当前全部组合已实测。
> [返回板卡索引](index.md) · [构建与刷写流程](../workflows/lunch-build-flash-流程.md)

## TL;DR

Radxa Dragon Q8B 基于 Qualcomm SC8280XP，使用 SPI 中的签名 XBL/EDK2、GRUB
和 4096 字节 LBA UFS。仓库已能生成 Ubuntu 24.04 ESP + rootfs 整盘镜像，并通过 EDL 刷写。

## 板级契约

- kernel/DTB：`linux-7.0.11` 浮动分支与 `sc8280xp-radxa-dragon-q8b.dtb`。
- 固件：声明式安装 ADSP/CDSP/SLPI/VPU/QUP/display 固件和 Radxa ALSA UCM deb。
- USB：`a600000.usb` 固定 peripheral 供 adbd，`a800000.usb` 保持 host；同时复用 DWC3 clear-stall 修复。
- 网络：QPS615/TC956x 双 MAC 保留；板级 patch 清零 IRQ-domain 配置结构，避免随机栈值导致 `-EINVAL`。
- UFS：支持 `lun0-only` 和 `qcom` 两种一次性初始化布局。

## 当前状态

系统镜像已有启动基线；USB gadget 与双网口的后续修复已通过配置测试和 patch check。HDMI 热插拔、可换无线模组和完整外设回归仍需实板验收。
