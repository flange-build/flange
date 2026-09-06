---
title: 双 extlinux 配置
type: concept
status: stable
sources:
  - ProjectSpec.md#24-usb-线刷-recovery
  - builder/extlinux.py
  - builder/platforms/rockchip/boot.py
  - docs/recovery.md
related:
  - "[[U-Boot 启动链]]"
  - "[[boot-once 启动切换]]"
  - "[[recovery 系统]]"
updated: 2026-09-05
---

## TL;DR

boot 分区生成两份 extlinux 配置：`extlinux/extlinux.conf`（normal，DEFAULT=flange）和 `extlinux/recovery.conf`（recovery，DEFAULT=flange-recovery）。两份文件共用同一内核，通过不同 `root=PARTLABEL=` 选择系统分区。

本页以已启用 Recovery 的 Rockchip extlinux 启动路径为例；先确认自己的板卡支持该机制，使用步骤见 [Recovery 指南](../../docs/recovery.md)。其他平台应核对各自 boot 策略。

## 关键设计要点

- **normal 配置**：`NORMAL_CONFIG = "extlinux.conf"`；label 名 `NORMAL_LABEL = "flange"`；cmdline 指向 `root=PARTLABEL=rootfs`
- **recovery 配置**：`RECOVERY_CONFIG = "recovery.conf"`；label 名 `RECOVERY_LABEL = "flange-recovery"`；cmdline 额外追加 `flange.mode=recovery`，指向 `root=PARTLABEL=recovery`
- **DEFAULT 不被持久修改**：boot-once 机制只改变本次 U-Boot 选哪份文件，extlinux.conf 本身的 DEFAULT 始终指向 normal，recovery 进入不会留下持久切换痕迹
- **`set_default_label()` 的用途**：纯字符串变换工具，用于兼容 fallback 或手工修复场景，不是常规流程
- **内核共享**：Rockchip 的两份配置引用相同的 `/extlinux/Image` 和 DTB 路径，这些路径相对于 boot 分区根目录；recovery 分区挂载后有自己独立的 rootfs，无需单独的 kernel 镜像

## 关键代码位置

- [`builder/extlinux.py:NORMAL_CONFIG / RECOVERY_CONFIG`](../../builder/extlinux.py) — 文件名常量，L27-L28
- [`builder/extlinux.py:render_extlinux`](../../builder/extlinux.py) — 渲染函数，L45

## 延伸阅读

- [Recovery 指南](../../docs/recovery.md)
- [启动配置生成](../../builder/platforms/rockchip/boot.py)
