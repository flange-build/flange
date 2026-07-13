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
updated: 2026-07-14
---

## TL;DR

宿主机刷写策略抽象层；把“本地产物预检、设备准备、整盘/具名分区写入、重启”与构建系统解耦。Rockchip 同时支持块设备 GPT 与 SPI NAND MTD，其他平台通过同一接口扩展。

## 关键设计要点

- **抽象接口**：`FlashStrategy` 定义 `preflight`、`pre_flash/pre_flash_all`、`write_partition/write_named_partition`、`flash_whole_disk`、`write_gpt`、`reboot`
- **块设备**：Maskrom 时 DB 上传 loader，可选 SSD 切介质；GPT/分区按 WL 或 DI 写入，延续既有 eMMC/UFS 路径
- **SPI NAND**：DB 后先验 SoC/介质，`UL -noreset` 持久写 loader，`DI -p` 写 parameter，再按名称写 uboot/boot/amp/rootfs；loader 不支持 SSD 时不做无意义介质切换
- **安全门禁**：检测多设备立即拒绝；任何设备写入前校验 parameter SHA-256、容量、rootfs MTD index、镜像存在与大小
- **自动设备检测**：`wait_for_device()` 轮询 `detect_device()`（upgrade_tool LD），带 spinner UI 和超时友好提示（30s 默认）
- **GPT 刷新**：块设备 `write_gpt()` 从 raw.img 截取 LBA 1-33；UFS/SPI NAND 由 `DI -p parameter.txt` 处理，不重复 WL GPT
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
