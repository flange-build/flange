---
title: radxa-cubie-a7z
type: board
status: wip
sources:
  - components/board/radxa-cubie-a7z/config.py
  - components/board/radxa-cubie-a7z/overlay/etc/usbdevice.conf
related:
  - "[[allwinnera733 平台]]"
  - "[[lunch-build-flash 流程]]"
  - "[[新增板级支持]]"
updated: 2026-04-26
---

## TL;DR

Radxa Cubie A7Z，Allwinner A733 SoC，A733 平台首块落地板，刷写工具为 `dd`（非 upgrade_tool），进行中。

## product / variant

继承 allwinnera733 平台默认：`products: [default]`，`variants: [debug, release]`。

```
lunch radxa-cubie-a7z-default-debug
lunch radxa-cubie-a7z-default-release
```

## 关键差异点

| 项 | 值 |
|---|---|
| DTB | `sun60i-a733-cubie-a7z` |
| kernel_device.board_dts_path | `configs/cubie_a7z/linux-5.15/board.dts` |
| bootloader target | `radxa-cubie-a7z` |
| root 密码 | `1234` |
| 刷写工具 | `dd`（平台层定义） |

A733 平台使用 `kernel_device.board_dts_path` 指定设备树源文件路径，与 Rockchip 平台使用 `kernel.dts` 直接引用 DTB target 的机制不同。

## overlay

仅 `overlay/etc/usbdevice.conf`，hostname 未定制。
