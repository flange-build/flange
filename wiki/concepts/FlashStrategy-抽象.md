---
title: FlashStrategy 抽象
type: concept
status: stable
sources:
  - builder/flash.py
  - openspec/specs/allwinnera733-flash/spec.md
related:
  - "[[flash-config.json]]"
  - "[[USB 线刷协议]]"
  - "[[rockchip 平台]]"
  - "[[allwinnera733 平台]]"
updated: 2026-04-26
---

## TL;DR

宿主机刷写策略抽象层；各平台实现 `find_tool / detect_device / pre_flash / write_partition / reboot` 接口。当前有 `RockchipFlashStrategy`，Allwinner 策略待实现。

## 关键设计要点

- **抽象接口**：`FlashStrategy` ABC 定义 `find_tool`、`detect_device`、`pre_flash`、`write_partition`、`write_gpt`、`reboot`、`partition_image_map` 等方法
- **Rockchip 实现**：`RockchipFlashStrategy` 使用 `upgrade_tool`；DB 上传 miniloader（maskrom 模式）→ WL 写入各分区→ RD 重启
- **自动设备检测**：`wait_for_device()` 轮询 `detect_device()`（upgrade_tool LD），带 spinner UI 和超时友好提示（30s 默认）
- **GPT 刷新**：`write_gpt()` 从 raw.img 截取 LBA 1-33 写入，确保内核看到新分区表（新增 recovery 分区后必须执行）
- **任意分区级刷写**：`flange flash <partition-name>` 仅写指定分区；`flange flash --raw /dev/sdX` 整盘 dd
- **未来 Allwinner**：`sunxi-fel` / PhoenixSuit / FEL 模式，通过实现新 `AllwinnerFlashStrategy` 子类注入，不改框架

## 关键代码位置

- [`builder/flash.py:FlashStrategy`](../../builder/flash.py) — 抽象基类，L136
- [`builder/flash.py:RockchipFlashStrategy`](../../builder/flash.py) — Rockchip 实现，L206
- [`builder/flash.py:FlashStrategy.wait_for_device`](../../builder/flash.py) — 设备检测轮询，L177

## 延伸阅读

- [[flash-config.json]]
- [[USB 线刷协议]]
- [[rockchip 平台]]
