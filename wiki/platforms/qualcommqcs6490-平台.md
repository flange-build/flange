---
title: qualcommqcs6490 平台
type: platform
status: wip
sources:
  - builder/platforms/qualcommqcs6490/
  - components/platform/qualcommqcs6490/config.py
  - components/platform/qualcommqcs6490/qcs6490/config.py
  - builder/flash.py
related:
  - "[[radxa-dragon-q6a]]"
  - "[[qualcommsc8280xp 平台]]"
  - "[[FlashStrategy 抽象]]"
updated: 2026-08-24
---

## TL;DR

QCS6490 平台走 XBL → EDK2 UEFI → GRUB → Linux，系统盘是 4096 字节 LBA 的
UFS，刷写使用 `edl-ng`。当前内核固定在 `radxa/kernel@linux-7.0.2`
commit `7473a9f`，不再使用早期 6.6.90 BSP。

## 关键设计

- UFS/SCSI/QMP PHY 和 interconnect 必须 built-in，因为 flange 不生成 initramfs。
- ESP 只放 GRUB EFI 与菜单；kernel/DTB 位于 rootfs `/boot`。`fstab` 不挂载 ESP。
- `flange flash` 只写 UFS `raw.img`；`--spi-firmware` 单独更新 EDK2 SPI 固件。
- 全新 UFS 先用 `--provision-ufs lun0-only|qcom` 建立 LUN 布局，重进 EDL 后再刷系统盘。

## 易踩坑

7.0.2 需与当前 SPI 固件配套；旧固件会在 UFS probe 阶段引发整机复位。
Q6A 的实机能力和屏幕适配见 [[radxa-dragon-q6a]]。
