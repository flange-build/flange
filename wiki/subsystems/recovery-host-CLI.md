---
title: recovery-host-CLI
type: subsystem
status: stable
sources:
  - builder/recovery_host.py
related:
  - "[[recovery 在线刷写流程]]"
  - "[[recovery 系统]]"
  - "[[recoveryctl 协议]]"
  - "[[recoveryctl]]"
updated: 2026-04-26
---

## TL;DR

`builder/recovery_host.py` 实现宿主机端 `flange recovery` 命令组；通过 `AdbTransport` 与设备上的 `recoveryctl` 通信，编排 enter/list/flash/backup/shell/reboot 六个子命令。

## 关键设计要点

- **Transport 抽象**：`Transport` ABC 定义 `wait`、`push`、`pull`、`shell`、`exec_in` 接口；`AdbTransport` 封装 `adb` 子进程并解析返回码
- **设备模式查询**：`query_device_mode` 轮询 `recoveryctl mode`，最多 8 次重试；`require_recovery_mode` 在非 recovery 模式时抛出异常
- **enter**：`cmd_enter` 发 `boot-once` 重启，`wait(timeout=90)` 等待 ADB 重连，再确认模式
- **flash**：本地计算 size/SHA256，通过 `adb exec-in` 调 `recoveryctl flash --size <n> --sha256 <hash>`，镜像数据直接走 stdin；protected 分区要求输入 `YES` 并默认读回校验
- **backup/shell/reboot**：pull 分区镜像 / 交互 adb shell / 发 reboot 命令
- **错误路径**：`shell` 返回非零抛 `HostRecoveryError`；`main` 捕获后彩色打印并 `sys.exit(1)`

## 关键代码位置

- [`builder/recovery_host.py:AdbTransport`](../../builder/recovery_host.py) — ADB 实现，L74
- [`builder/recovery_host.py:cmd_enter`](../../builder/recovery_host.py) — enter 子命令，L251
- [`builder/recovery_host.py:cmd_flash`](../../builder/recovery_host.py) — flash 子命令，L315
- [`builder/recovery_host.py:query_device_mode`](../../builder/recovery_host.py) — 模式查询，L203
- [`builder/recovery_host.py:build_argparser`](../../builder/recovery_host.py) — 命令行解析，L425
