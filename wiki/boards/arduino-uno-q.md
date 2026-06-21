---
title: arduino-uno-q
type: board
status: wip
sources:
  - components/board/arduino-uno-q/config.py
  - components/platform/qualcommqrb2210/config.py
  - components/platform/qualcommqrb2210/qrb2210/config.py
  - builder/platforms/qualcommqrb2210/
  - builder/flash.py#QualcommQrb2210FlashStrategy
  - openspec/changes/add-qrb2210-arduino-uno-q/
related:
  - "[[qualcommqrb2210 平台]]"
  - "[[radxa-dragon-q6a]]"
  - "[[FlashStrategy 抽象]]"
updated: 2026-06-21
---

## TL;DR

Arduino UNO Q，Qualcomm Dragonwing **QRB2210 / QCM2290**（代号 Imola/UnoQ）单板，
eMMC 存储，板载 ath10k Wi-Fi/BT。SoC（QRB2210 MPU）+ STM32U585 MCU 双芯架构（flange
只管 Linux/QRB2210 侧）。flange 第二块 Qualcomm 板，验证 **U-Boot extlinux + qdl 按分区
刷 + Adreno 702 freedreno** 全栈——与 [[radxa-dragon-q6a]]（UEFI/GRUB）互补的高通形态。

> ⚠️ 尚未实板 bring-up。配置/构建器/刷写策略已落地并经 Python 级验证；Docker 编译、
> vendor 固件包、实板启动均待验证。详见 openspec change `add-qrb2210-arduino-uno-q`。

## 三层配置

- `platform=qualcommqrb2210`（[[qualcommqrb2210 平台]]）
- `soc=qrb2210`：mainline Linux v7.0 + `qrb2210-arduino-imola.dtb`，eMMC 512 扇区
- `board=arduino-uno-q`：仅声明 board/soc/platform + dtb，其余沿用 SoC 层

lunch target：`arduino-uno-q-default-{debug,release}`（product/variant 机制自动生成）。

## 启动与刷写

- 启动链：`PBL→XBL→TZ/HYP→ABL→U-Boot(Android boot.img)→extlinux(sysboot)→Linux`
- boot 分区（ext4，label `boot`）：`/extlinux/extlinux.conf` + Image + dtb
- rootfs 分区（ext4，label `rootfs`）：ubuntu-base noble + Mesa freedreno + ath10k 固件
- 刷写：JCTL 跳线进 EDL → `qdl --allow-missing --storage emmc` 按分区刷 boot/rootfs；
  vendor 固件（XBL/ABL/TZ/HYP/U-Boot/GPT）bring-up 一次性 `flange flash --spi-firmware`

## 外设

- **GPU**：Adreno 702，开源 Mesa freedreno(GL)/turnip(Vulkan) + 内核 drm/msm + linux-firmware
- **Wi-Fi**：mainline ath10k（无 AIC8800 OOT）
- **串口**：GENI UART，`console=ttyMSM0,115200`

## 待办（bring-up）

- vendor rawprogram 的 boot/rootfs label/sector 校正（Armbian 提及 boot 在 partition 43）
- U-Boot load 地址是否需定制 boot 脚本（规避 ABL 保留内存区）
- mainline v7.0 arm64 defconfig 外设核对（DRM_MSM/ATH10K/eMMC/GENI）
- Adreno 702 固件在 noble linux-firmware 的落点确认
- 实板启动链 + GPU/Wi-Fi/网络/存储验证

详见 openspec `add-qrb2210-arduino-uno-q` tasks.md。
