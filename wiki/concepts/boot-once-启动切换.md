---
title: boot-once 启动切换
type: concept
status: stable
sources:
  - ProjectSpec.md#24-usb-线刷-recovery
  - builder/recovery.py
  - docs/recovery.md
related:
  - "[[reboot reason]]"
  - "[[双 extlinux 配置]]"
  - "[[recovery 系统]]"
  - "[[U-Boot 启动链]]"
updated: 2026-04-26
---

## TL;DR

通过 Linux `reboot(2)` RESTART2 系统调用传递 `"recovery"` 字符串，让 U-Boot 本次选择 `recovery.conf` 启动；可选 `flange_boot_once=recovery` U-Boot env 作为断电保持兜底。不持久修改 extlinux DEFAULT。

## 关键设计要点

- **主路径**：`recoveryctl recovery` 子命令调用 `ctypes` 直接调用 `reboot(LINUX_REBOOT_CMD_RESTART2, "recovery")`；kernel reboot-mode driver 将原因写入平台 PMU 寄存器
- **U-Boot 读取**：U-Boot 启动时检查 PMU 寄存器，匹配 recovery 原因后将 sysboot 目标从 `extlinux.conf` 切换到 `recovery.conf`；**读取后清除**（one-shot 语义）
- **兜底路径 `flange_boot_once`**：U-Boot env 变量，断电后仍保持；U-Boot 读取该变量后清除，确保下次正常启动
- **设计取舍**：不持久修改 DEFAULT 是为了防止 recovery 进入失败时系统永久陷入 recovery 循环；one-shot 语义保证安全性
- **关键 commit**：commit 33bc2c2 实现此机制

## 关键代码位置

- [`components/app/recoveryctl/bin/recoveryctl`](../../components/app/recoveryctl/bin/recoveryctl) — `BOOT_ONCE_ENV` (L57)、`LINUX_REBOOT_CMD_RESTART2` (L67)
- [`builder/extlinux.py:RECOVERY_CONFIG`](../../builder/extlinux.py) — recovery.conf 文件名，L28

## 延伸阅读

- [[reboot reason]]
- [[双 extlinux 配置]]
- [[recovery 系统]]
