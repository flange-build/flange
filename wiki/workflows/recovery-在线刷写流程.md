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
updated: 2026-04-30
---

## TL;DR

normal 启动 → `flange recovery enter` → boot-once 切换到 recovery → adb forward + TCP socket 在线刷写 → `flange recovery reboot` 回 normal。数据面走 `adb forward + 设备端 127.0.0.1 TCP listen`，控制面走 `adb shell` 的 stdout 单行 ASCII 控制行（`PORT=`/`READY`/`PROGRESS:`/`STATUS:OK`/`STATUS:FAIL:`）。

## Host → Device 时序

```
flange recovery enter
  → adb shell recoveryctl recovery → reboot("recovery")
  → U-Boot 读 boot reason → recovery.conf → recovery rootfs
  → adbd + recoveryctl 待命

flange recovery flash rootfs rootfs.img
  host                              device
   │ adb shell recoveryctl flash ──► preflight + flash_lock
   │   --size N --sha256 H
   │   --listen tcp:0
   │ ◄── PORT=<n>                    bind 127.0.0.1:<n>, listen
   │ ◄── READY                       listen 就绪
   │ adb forward tcp:0 tcp:<n> ───►
   │ connect 127.0.0.1:<L>           accept (timeout 30s)
   │ ═══ TCP socket 数据流 ═════════ recv → write → sha256
   │ ◄── PROGRESS:<sent>/<total>     边写边汇报（host 自己也跟踪 sent）
   │ ◄── STATUS:OK                   fsync / sync 完成
   │ ◄── __flange_rc__=0             host transport wrap 注入
   │ adb forward --remove tcp:<L>

flange recovery reboot
  → recoveryctl normal → 普通 reboot → normal
```

## 子命令说明

| 子命令 | 作用 |
|---|---|
| `enter` | 触发 boot-once 写入，重启进入 recovery |
| `list` | 拉取并格式化可操作分区清单 |
| `flash <part> <img>` | adb shell 起设备端 listener；本地计算 sha256，4MiB chunk 通过 adb forward + TCP socket 写入 |
| `backup <part> <out>` | adb shell 起设备端 listener；从 socket 读分区数据写 `<out>.partial`，`STATUS:OK` 后 `os.replace` 原子改名 |
| `shell` | 打开交互式 ADB shell |
| `reboot [target]` | 请求 normal/recovery/loader 并重启 |

## 关键实现位置

- [`builder/recovery_host.py`](../../builder/recovery_host.py) — 宿主机 CLI；`Transport` ABC + `AdbTransport` + `run_listener_session()` 编排 helper
- [[recoveryctl]] — 设备端二进制（`components/app/recoveryctl/`），实现 `--listen tcp:<port>` listener 状态机

## 安全策略提示

bootloader 和 recovery 分区默认 protected；强制写入须宿主机交互确认 `YES`，且设备端要求 `--sha256` 并默认读回校验（host 端 `--verify-readback`）。详见 [[recovery 系统]] 中的安全策略节。
