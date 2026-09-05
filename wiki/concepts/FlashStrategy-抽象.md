---
title: FlashStrategy 抽象
type: concept
status: stable
sources:
  - builder/flash/strategy.py
  - builder/flash/plan.py
  - builder/flash/execute.py
  - openspec/specs/allwinnera733-flash/spec.md
  - builder/flash/model.py
  - docs/development-guide.md
related:
  - "[[flash-config.json]]"
  - "[[USB 线刷协议]]"
  - "[[rockchip 平台]]"
  - "[[allwinnera733 平台]]"
updated: 2026-09-05
---

## TL;DR

宿主机刷写策略抽象层；把“本地产物预检、设备准备、整盘/具名分区写入、重启”与构建系统解耦。Rockchip 同时支持块设备 GPT 与 SPI NAND MTD，其他平台通过同一接口扩展。

构建期计划位于 [`flash/plan.py`](../../builder/flash/plan.py)，数据模型在
[`flash/model.py`](../../builder/flash/model.py)，宿主执行位于 `strategy.py` 与 `execute.py`。
开始操作前先读[开发指南](../../docs/development-guide.md)并核对[板卡页](../boards/index.md)。

## 关键设计要点

- **抽象接口**：`FlashStrategy` 定义 `preflight`、`pre_flash/pre_flash_all`、`write_partition/write_named_partition`、`flash_whole_disk`、`write_gpt`、`reboot`
- **块设备**：Maskrom 时 DB 上传 loader，可选 SSD 切介质；GPT/分区按 WL 或 DI 写入，延续既有 eMMC/UFS 路径
- **SPI NAND**：DB 后先验 SoC/介质，`UL -noreset` 持久写 loader，`DI -p` 写 parameter，再按名称写 uboot/boot/amp/rootfs；loader 不支持 SSD 时不做无意义介质切换
- **安全门禁**：检测多设备立即拒绝；任何设备写入前校验 parameter SHA-256、容量、rootfs MTD index、镜像存在与大小
- **自动设备检测**：`wait_for_device()` 轮询 `detect_device()`（upgrade_tool LD），带 spinner UI 和超时友好提示（30s 默认）
- **GPT 刷新**：块设备 `write_gpt()` 从 raw.img 截取 LBA 1-33；UFS/SPI NAND 由 `DI -p parameter.txt` 处理，不重复 WL GPT
- **任意分区级刷写**：`flange flash <partition-name>` 仅写指定分区；`flange flash --raw /dev/sdX` 整盘 dd
- **当前平台**：Allwinner 使用 `dd` 整盘路径；Amlogic 使用 pyamlboot + fastboot；Qualcomm 使用 edl-ng。FEL/PhoenixSuit 是尚未实现的扩展方向，具体路由见[平台索引](../platforms/index.md)

## 关键代码位置

- [`builder/flash/strategy.py:FlashStrategy`](../../builder/flash/strategy.py) — 抽象基类，L136
- [`builder/flash/strategy.py:RockchipFlashStrategy`](../../builder/flash/strategy.py) — Rockchip 实现，L206
- [`builder/flash/strategy.py:FlashStrategy.wait_for_device`](../../builder/flash/strategy.py) — 设备检测轮询，L177

## 延伸阅读

- [[flash-config.json]]
- [[USB 线刷协议]]
- [[rockchip 平台]]
