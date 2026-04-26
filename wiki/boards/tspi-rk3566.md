---
title: tspi-rk3566
type: board
status: stable
sources:
  - components/board/tspi-rk3566/config.py
  - components/board/tspi-rk3566/patches/kernel/0001-dts-firmware_class-path-fix.patch
  - components/board/tspi-rk3566/patches/kernel/0002-bcmdhd-set-fw-ampak-path-brcm.patch
  - components/board/tspi-rk3566/overlay/etc/hostname
  - components/board/tspi-rk3566/overlay/etc/usbdevice.conf
related:
  - "[[rockchip 平台]]"
  - "[[lunch-build-flash 流程]]"
  - "[[新增板级支持]]"
updated: 2026-04-26
---

## TL;DR

TSpi RK3566 开发板，板载 AP6212A WiFi/BT 模组（AMPAK），需要 kernel 补丁修正固件加载路径。

## product / variant

继承平台默认：`products: [default]`，`variants: [debug, release]`。

```
lunch tspi-rk3566-default-debug
lunch tspi-rk3566-default-release
```

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
