---
title: U-Boot 启动链
type: concept
status: stable
sources:
  - ProjectSpec.md#24-usb-线刷-recovery
  - builder/extlinux.py
  - docs/recovery.md
related:
  - "[[双 extlinux 配置]]"
  - "[[boot-once 启动切换]]"
  - "[[bootloader 构建器]]"
updated: 2026-04-26
---

## TL;DR

上电 → SPL（miniloader）→ U-Boot → 扫描 boot 分区 extlinux 配置 → 加载 kernel + DTB → 启动。normal 与 recovery 的分叉点在 U-Boot 选择哪份 extlinux conf。

## 关键设计要点

- **SPL（Secondary Program Loader）阶段**：`idbloader.img` 包含 DDR init 和 miniloader，由刷写工具写入固定 raw 偏移（Rockchip 为 0x40 sector）
- **U-Boot 阶段**：`u-boot.itb` 由 SPL 加载；提供 distro_bootcmd 标准，扫描 boot 分区的 `extlinux/` 目录
- **extlinux 选择逻辑**：正常启动读 `extlinux/extlinux.conf`；检测到 reboot reason 或 boot-once 状态时读 `extlinux/recovery.conf`
- **extlinux 职责**：只描述"如何启动"（kernel 路径、DTB 路径、cmdline）；不决定"进哪个系统" — 后者由 U-Boot reboot reason 逻辑决定
- **Rockchip 实现**：`fdt` 指令指定 DTB；Allwinner 使用 `devicetree` 指令（`extlinux.py:LabelSpec.fdt_directive`）

## 关键代码位置

- [`builder/extlinux.py`](../../builder/extlinux.py) — `render_extlinux`、`NORMAL_CONFIG`、`RECOVERY_CONFIG` 常量，L1-L30
- [`docs/recovery.md`](../../docs/recovery.md) — 分区布局与启动流程用户文档

## 延伸阅读

- [[双 extlinux 配置]]
- [[boot-once 启动切换]]
- [[bootloader 构建器]]
