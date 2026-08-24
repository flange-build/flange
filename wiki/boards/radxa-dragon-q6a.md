---
title: radxa-dragon-q6a
type: board
status: wip
sources:
  - components/board/radxa-dragon-q6a/config.py
  - components/platform/qualcommqcs6490/qcs6490/config.py
  - components/platform/qualcommqcs6490/patches/
  - components/packages/meizu-e3-panel/package.py
  - builder/platforms/qualcommqcs6490/
  - builder/flash.py
  - openspec/changes/add-qcs6490-radxa-dragon-q6a/
  - openspec/changes/archive/2026-05-31-migrate-qcs6490-kernel-702/
related:
  - "[[qualcommqcs6490 平台]]"
  - "[[FlashStrategy 抽象]]"
  - "[[硬件特性包]]"
  - "[[构建期 dtb overlay 合并]]"
updated: 2026-08-24
---

## TL;DR

Radxa Dragon Q6A 基于 QCS6490，使用 UEFI/GRUB、4K LBA UFS 和 EDL 刷写。实机已验证 UFS 启动、Adreno 643 freedreno/turnip、AIC8800 Wi-Fi、RTL8168 有线网、ADB、ADSP/CDSP 与硬件视频编解码。

## 当前契约

- kernel 固定在 `radxa/kernel@linux-7.0.2` commit `7473a9f`，按
  `defconfig → qcom_module.config → radxa.config → radxa_custom.config` 叠加。
- `default` 为基础产品；`meizu-e3-bringup` 通过构建期 DTB overlay 合并接入 1080×2160 DSI 屏、SGM37604A 背光和 sec_ts 触摸，三者已上板。
- 硬件编码需在 UEFI 开启 Hypervisor Override，让 Linux 从 EL2 启动；EL1 下喂帧会整机复位。

## 刷写

`flange flash` 只写 UFS `raw.img`，`flange flash --spi-firmware` 只更新 SPI EDK2 固件。7.0.2 必须配套当前 SPI 固件，旧版会在 UFS probe 时复位。

全新 UFS 先用 `--provision-ufs lun0-only|qcom` 建立 LUN 布局；该操作会重建存储布局，完成后需重新进入 EDL，再执行 `flange flash`。
