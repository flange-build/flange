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
updated: 2026-07-14
---

## TL;DR

各平台使用不同 USB 协议与宿主机刷写工具通信，设备需先进入下载模式（Maskrom/FEL/EDL）。与 ADB 在线刷写不同，线刷可重写 bootloader 和整盘。

## 关键设计要点

- **Rockchip 块设备（`upgrade_tool`）**：Maskrom/Loader → LD 检测 → DB（必要时）→ SSD（多介质板可选）→ WL/DI 写分区 → RD
- **Rockchip SPI NAND**：Maskrom → DB 临时启动 loader → RCI/RFI/RID 身份门禁 → `UL -noreset` → `DI -p parameter.txt` → 具名 `DI` → RD；由 loader 处理 OOB/ECC/坏块，禁止按 LBA `WL`
- **Allwinner（`sunxi-fel` / PhoenixSuit）**：FEL 模式（长按 FEL 按键或 dipswitch）→ sunxi-fel 用于低层操作；PhoenixSuit/LiveSuit 用于完整镜像烧录；Radxa Cubie A7Z 使用此方案
- **Qualcomm（QDL / QFIL / EDL）**（计划中，未实现）：Emergency Download Mode（EDL）通过 9008 端口；`QDL`/`QFIL` 工具写入各分区
- **进入下载模式方式**：按键组合（最常见）/ dipswitch 拨码开关 / 软件命令（`recoveryctl loader`）/ 短接焊盘
- **与 ADB 在线刷写的区别**：线刷重写 bootloader 和 raw 分区，设备无需启动；ADB 刷写通过设备端 `recoveryctl` 操作，只能访问可挂载分区，不能改 bootloader

## 关键代码位置

- [`builder/flash.py:RockchipFlashStrategy`](../../builder/flash.py) — Rockchip 块设备与 SPI NAND 路由
- [openspec/specs/allwinnera733-flash/spec.md](../../openspec/specs/allwinnera733-flash/spec.md) — Allwinner 刷写方案规格

## 延伸阅读

- [[FlashStrategy 抽象]]
- [[rockchip 平台]]
- [[allwinnera733 平台]]
