---
title: tspi-rk3566
type: board
status: stable
sources:
  - components/board/tspi-rk3566/config.py
  - components/board/tspi-rk3566/patches/kernel/0001-dts-firmware_class-path-fix.patch
  - components/board/tspi-rk3566/patches/kernel/0002-bcmdhd-set-fw-ampak-path-brcm.patch
  - components/board/tspi-rk3566/patches/kernel/0003-add-tspi-rk3566-amp-dts.patch
  - components/board/tspi-rk3566/overlay/etc/hostname
  - components/board/tspi-rk3566/overlay/etc/usbdevice.conf
related:
  - "[[rockchip 平台]]"
  - "[[lunch-build-flash 流程]]"
  - "[[新增板级支持]]"
  - "[[AMP 协处理器与 rpmsg]]"
  - "[[amp 构建器]]"
updated: 2026-06-30
---

## TL;DR

TSpi RK3566 开发板，板载 AP6212A WiFi/BT 模组（AMPAK），需要 kernel 补丁修正固件加载路径。

## product / variant

`products: [default, amp, amp-rtt]`，`variants: [debug, release]`。

```
lunch tspi-rk3566-default-debug    # 常规 4 核 Linux
lunch tspi-rk3566-amp-debug        # AMP：cpu3 裸机 HAL 从核
lunch tspi-rk3566-amp-rtt-debug    # AMP：cpu3 跑 RT-Thread RTOS 从核
```

**amp product**：经条件键开 amp（`config.amp`，复用 rk3568 SDK，同 die）、选专用 amp dts（patch 0003）、加 rpmsg 字符设备、用含非 raw `amp` 分区的 product 作用域分区表、U-Boot 经 `bootloader.+defconfig:amp` 开 AMP loader。**amp-rtt product**：同 amp 但 `mode=rt-thread`（cpu3 跑 RTOS，`app:amp-rtt=rk3568_amp_rtt_demo`），dts/分区/U-Boot/内核驱动全复用 amp（条件键单值匹配、故各写一份 `:amp-rtt`；分区抽 `_AMP_PARTITIONS` 共享）。default 不受影响。机制见 [[AMP 协处理器与 rpmsg]]、构建见 [[amp 构建器]]。

## 关键差异点

| 项 | 值 |
|---|---|
| DTB | `tspi-rk3566-user-v10-ext39-linux` |
| bootloader commit | `3c60a711`（锁定版本） |
| rootfs 额外包 | `wpasupplicant` |
| root 密码 | `1234` |

## patches（kernel）

两个 kernel 补丁必须应用才能正常加载 AP6212A 固件：

- `0001-dts-firmware_class-path-fix.patch` — 修正 DTS 中 `firmware-class` 搜索路径
- `0002-bcmdhd-set-fw-ampak-path-brcm.patch` — bcmdhd 驱动固件路径指向 `brcm/`

固件本体（`.bin`/`.hcd`/nvram）通过 `rootfs.extra_firmware` 从 `radxa-pkg/radxa-firmware` 拉取，落在 `lib/firmware/brcm/`。

## overlay

`overlay/etc/hostname` + `overlay/etc/usbdevice.conf`，同平台其他板。
