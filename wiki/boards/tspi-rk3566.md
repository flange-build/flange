---
title: tspi-rk3566
type: board
status: stable
sources:
  - components/board/tspi-rk3566/config.jsonnet
  - components/board/tspi-rk3566/patches/kernel/0001-dts-firmware_class-path-fix.patch
  - components/board/tspi-rk3566/patches/kernel/0002-bcmdhd-set-fw-ampak-path-brcm.patch
  - components/board/tspi-rk3566/patches/kernel/0003-add-tspi-rk3566-amp-dts.patch
  - components/board/tspi-rk3566/overlay/etc/hostname
  - components/board/tspi-rk3566/overlay/etc/usbdevice.conf
  - components/board/tspi-rk3566/dtso/tspi-rk3566-amp-foc.dtso
  - docs/first-steps.md
related:
  - "[[rockchip 平台]]"
  - "[[lunch-build-flash 流程]]"
  - "[[新增板级支持]]"
  - "[[AMP 协处理器与 rpmsg]]"
  - "[[amp 构建器]]"
  - "[[rk3568_amp_rtt_foc]]"
updated: 2026-09-05
---

> 阅读前提：先完成[初学指南](../../docs/first-steps.md)的环境准备，运行
> `flange target list tspi-rk3566` 确认当前目标，再按该型号硬件说明匹配介质、接口与下载模式。
> 本页是配置摘要与硬件记录；下文验收只覆盖记录的版本、产品和测试项，不代表当前全部组合已实测。
> [返回板卡索引](index.md) · [构建与刷写流程](../workflows/lunch-build-flash-流程.md)

## TL;DR

TSpi RK3566 开发板，板载 AP6212A WiFi/BT 模组（AMPAK），需要 kernel 补丁修正固件加载路径。

## product / variant

`products: [default, amp, amp-rtt, foc]`，`variants: [debug, release]`。

```
lunch tspi-rk3566-default-debug    # 常规 4 核 Linux
lunch tspi-rk3566-amp-debug        # AMP：cpu3 裸机 HAL 从核
lunch tspi-rk3566-amp-rtt-debug    # AMP：cpu3 跑 RT-Thread RTOS 从核
lunch tspi-rk3566-foc-debug        # AMP：cpu3 RT-Thread 驱动三相无刷电机
```

**amp product**：Jsonnet 按 product 启用 amp（复用 rk3568 SDK，同 die）、选择专用设备树、通过 `kernel.config` 加 rpmsg 字符设备、切换 AMP 分区表，并通过 `bootloader.config` 开启 AMP loader。**amp-rtt product**：复用同一套配置，`mode=rt-thread` 且 cpu3 运行 RTOS。**foc product**：在 amp-rtt 基础上选择 `rk3568_amp_rtt_foc`，并经 `tspi-rk3566-amp-foc.dtso` 把 i2c2/pwm12-14/EN/FLIP 从 Linux 摘给从核独占。default 不受影响。机制见 [[AMP 协处理器与 rpmsg]]、构建见 [[amp 构建器]]。

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
