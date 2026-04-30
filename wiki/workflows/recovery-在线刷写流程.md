---
title: recovery 在线刷写流程
type: workflow
status: stable
sources:
  - builder/recovery_host.py
  - components/app/recoveryctl/
  - docs/recovery.md
  - openspec/specs/recovery-usb-flash/spec.md
related:
  - "[[recovery 系统]]"
  - "[[boot-once 启动切换]]"
  - "[[recoveryctl]]"
  - "[[recoveryctl 协议]]"
  - "[[recovery-host-CLI]]"
  - "[[adbd]]"
updated: 2026-04-26
---

## TL;DR

normal 启动 → `flange recovery enter` → boot-once 切换到 recovery → ADB 在线刷写 → `flange recovery reboot` 回 normal

## Host → Device 时序

```
flange recovery enter
  → adb shell recoveryctl recovery → reboot("recovery")
  → U-Boot 读 boot reason → recovery.conf → recovery rootfs
  → adbd + recoveryctl 待命

flange recovery flash rootfs rootfs.img
  → adb exec-in recoveryctl flash
  → recoveryctl 从 stdin 读多少写多少到分区

flange recovery reboot
  → recoveryctl normal → 普通 reboot → normal
```

## 子命令说明

| 子命令 | 作用 |
|---|---|
| `enter` | 触发 boot-once 写入，重启进入 recovery |
| `list` | 拉取并格式化可操作分区清单 |
| `flash <part> <img>` | exec-in 流式传输镜像 + 触发 recoveryctl 写分区 |
| `backup <part> <out>` | 触发 recoveryctl dump + pull 回宿主机 |
| `shell` | 打开交互式 ADB shell |
| `reboot [target]` | 请求 normal/recovery/loader 并重启 |

## 关键实现位置

- [`builder/recovery_host.py`](../../builder/recovery_host.py) — 宿主机 CLI，`cmd_enter` L251
- [[recoveryctl]] — 设备端二进制（`components/app/recoveryctl/`）

## 安全策略提示

bootloader 和 recovery 分区默认 protected；强制写入须宿主机交互确认 `YES`，且设备端要求 `--sha256` 并默认读回校验。详见 [[recovery 系统]] 中的安全策略节。
