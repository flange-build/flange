---
title: USB 线刷协议
type: concept
status: stable
sources:
  - builder/flash/strategy.py
  - builder/flash/execute.py
  - docs/recovery.md
  - openspec/specs/allwinnera733-flash/spec.md
related:
  - "[[FlashStrategy 抽象]]"
  - "[[rockchip 平台]]"
  - "[[allwinnera733 平台]]"
updated: 2026-09-05
---

## TL;DR

各平台使用不同 USB 协议与宿主机刷写工具通信，设备需先进入下载模式（Maskrom/FEL/EDL）。与 ADB 在线刷写不同，线刷可重写 bootloader 和整盘。

## 关键设计要点

- **Rockchip 块设备（`upgrade_tool`）**：Maskrom/Loader → LD 检测 → DB（必要时）→ SSD（多介质板可选）→ WL/DI 写分区 → RD
- **Rockchip SPI NAND**：Maskrom → DB 临时启动 loader → RCI/RFI/RID 身份门禁 → `UL -noreset` → `DI -p parameter.txt` → 具名 `DI` → RD；由 loader 处理 OOB/ECC/坏块，禁止按 LBA `WL`
- **Allwinner（当前 `dd`）**：当前 A733 路径写 SD 卡整盘镜像；FEL / PhoenixSuit 尚未实现。不要把芯片具备 FEL 模式等同于 flange 已支持该线刷流程
- **Qualcomm（edl-ng / EDL）**：Emergency Download Mode（紧急下载模式）通过 USB 9008，当前由 edl-ng 写 UFS；SPI 固件与 UFS 初始化是独立选项，见对应板卡页
- **进入下载模式方式**：各板可能使用按键、拨码、软件命令或指定硬件触点；只能按该型号官方硬件说明与[板卡记录](../boards/index.md)操作
- **与 ADB 在线刷写的区别**：线刷重写 bootloader 和 raw 分区，设备无需启动；ADB 刷写通过设备端 `recoveryctl` 和冻结的 Recovery 配置访问允许的分区；bootloader/raw 及 Recovery 自身默认受保护，强制写入契约见[Recovery 指南](../../docs/recovery.md)

## 关键代码位置

- [`builder/flash/strategy.py:RockchipFlashStrategy`](../../builder/flash/strategy.py) — Rockchip 块设备与 SPI NAND 路由
- [openspec/specs/allwinnera733-flash/spec.md](../../openspec/specs/allwinnera733-flash/spec.md) — Allwinner 刷写方案规格

## 延伸阅读

- [[FlashStrategy 抽象]]
- [[rockchip 平台]]
- [[allwinnera733 平台]]
