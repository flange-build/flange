---
title: USB 线刷协议
type: concept
status: stable
sources:
  - builder/flash.py
  - openspec/specs/allwinnera733-flash/spec.md
related:
  - "[[FlashStrategy 抽象]]"
  - "[[rockchip 平台]]"
  - "[[allwinnera733 平台]]"
updated: 2026-04-26
---

## TL;DR

各平台使用不同 USB 协议与宿主机刷写工具通信，设备需先进入下载模式（Maskrom/FEL/EDL）。与 ADB 在线刷写不同，线刷可重写 bootloader 和整盘。

## 关键设计要点

- **Rockchip（`upgrade_tool`）**：进入 Maskrom 模式（长按 BOOT 按键上电，或 `recoveryctl loader`）→ LD 检测 → DB 上传 miniloader → WL 写各分区 → RD 重启
- **Allwinner（`sunxi-fel` / PhoenixSuit）**：FEL 模式（长按 FEL 按键或 dipswitch）→ sunxi-fel 用于低层操作；PhoenixSuit/LiveSuit 用于完整镜像烧录；Radxa Cubie A7Z 使用此方案
- **Qualcomm（QDL / QFIL / EDL）**：Emergency Download Mode（EDL）通过 9008 端口；`QDL`/`QFIL` 工具写入各分区
- **进入下载模式方式**：按键组合（最常见）/ dipswitch 拨码开关 / 软件命令（`recoveryctl loader`）/ 短接焊盘
- **与 ADB 在线刷写的区别**：线刷重写 bootloader 和 raw 分区，设备无需启动；ADB 刷写通过设备端 `recoveryctl` 操作，只能访问可挂载分区，不能改 bootloader

## 关键代码位置

- [`builder/flash.py:RockchipFlashStrategy`](../../builder/flash.py) — Rockchip DB/WL/RD 实现，L206
- [openspec/specs/allwinnera733-flash/spec.md](../../openspec/specs/allwinnera733-flash/spec.md) — Allwinner 刷写方案规格

## 延伸阅读

- [[FlashStrategy 抽象]]
- [[rockchip 平台]]
- [[allwinnera733 平台]]
