---
title: reboot reason
type: concept
status: stable
sources:
  - builder/recovery.py
  - components/app/recoveryctl/bin/recoveryctl
  - docs/recovery.md
related:
  - "[[boot-once 启动切换]]"
  - "[[recovery 系统]]"
updated: 2026-04-26
---

## TL;DR

Linux 内核通过 `reboot(2)` 系统调用的 RESTART2 命令传递字符串重启原因；U-Boot 在下次启动时读取 SoC 平台寄存器（通常为 PMU/RTC 寄存器）获得该原因，据此选择启动路径后清除。

## 关键设计要点

- **系统调用接口**：`reboot(MAGIC1, MAGIC2, LINUX_REBOOT_CMD_RESTART2, arg)` — arg 为以 `\0` 结尾的字符串，内核传给平台 restart handler
- **Rockchip 实现**：kernel reboot-mode driver 将字符串哈希写入 PMU `GRF` 寄存器；U-Boot SPL 或 U-Boot 主体在启动早期读取并清除
- **平台差异**：Allwinner 使用 RTC 寄存器；Qualcomm 使用 IMEM scratch 寄存器；具体寄存器地址与 driver 实现因 SoC 而异，需查 BSP 文档
- **recoveryctl 实现**：直接通过 `ctypes` 调用 syscall，不依赖 `/sbin/reboot` 命令；支持 `aarch64`、`armv7l`、`x86_64` 的 syscall 号映射（L68-L74 in recoveryctl）
- **原子 one-shot**：U-Boot 读取原因后立即清除；断电重启不携带原因，恢复正常启动

## 关键代码位置

- [`components/app/recoveryctl/bin/recoveryctl`](../../components/app/recoveryctl/bin/recoveryctl) — 系统调用号表与调用逻辑，L65-L74
- [`docs/recovery.md`](../../docs/recovery.md) — 用户视角的 reboot reason 说明

## 延伸阅读

- [[boot-once 启动切换]]
- [[recovery 系统]]
