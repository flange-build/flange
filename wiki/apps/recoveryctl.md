---
title: recoveryctl
type: app
status: stable
sources:
  - components/app/recoveryctl/bin/recoveryctl
  - components/app/recoveryctl/app.yaml
  - builder/recovery_host.py
related:
  - "[[recovery 系统]]"
  - "[[recoveryctl 协议]]"
  - "[[recovery-host-CLI]]"
  - "[[recovery 在线刷写流程]]"
  - "[[adbd]]"
updated: 2026-04-30
---

## TL;DR

device 端 recovery CLI，运行于 recovery rootfs（也安装于 normal rootfs）。宿主机通过 `adb shell` 起会话，flash/backup 数据面走 `--listen tcp:<port>` 在 127.0.0.1 监听 + host 端 `adb forward` + TCP socket；危险操作在 recovery 模式下才生效。

## 关键设计要点

- **命令集**：`mode`、`list`、`flash`、`backup`、`recovery`、`loader`、`normal`、`reboot`；详见 [[recoveryctl 协议]]，本页不复刻。`flash-stream` 历史名已移除
- **典型调用形式**：
  - `recoveryctl flash <part> --size N --sha256 H --listen tcp:<port> [--force --verify-readback]`
  - `recoveryctl backup <part> --listen tcp:<port> [--compress zstd|none]`
- **实现语言**：Python 3，依赖标准库（`argparse`、`json`、`pathlib`、`hashlib`、`socket`）；`app.yaml` 中 `depends: [python3, util-linux, e2fsprogs]`
- **模式守卫**：`flash`、`backup` 等操作先调用 `_require_recovery_mode()` 检查 `/proc/cmdline`，normal 模式拒绝执行
- **安全要求**：`flash` 强制要求 `--size <n>` 与 `--sha256 <hex>`，设备端在 `accept` 前完成 preflight（分区存在 / 未挂载 / 容量够 / protected 策略 / 取 flash_lock），从 socket 读多少就写多少并同步核验数据完整性
- **不依赖 `exec:` / `shell:v2`**：flange 选用的 adbd（android-tools-4.2.2）不支持，所以 `--listen tcp:<port>` 是唯一可用的数据面
- **app.yaml 元数据**：`type: exec`，`arch: [aarch64, armhf]`，`build.system: none`（无编译步骤）
- **安装路径**：`bin/recoveryctl → /usr/sbin/recoveryctl`
- **打包入 rootfs**：由 [[deb 打包引擎]] 将 app.yaml 转为 .deb，[[recovery 构建器]] 在 chroot 阶段安装进 recovery rootfs

## 关键代码位置

- [`components/app/recoveryctl/bin/recoveryctl`](../../components/app/recoveryctl/bin/recoveryctl) — 全量实现，含 `FlashRequest`、`BackupRequest`、`do_flash()`、`do_backup()`、`cmd_*()` 等入口
- [`components/app/recoveryctl/app.yaml`](../../components/app/recoveryctl/app.yaml) — 打包元数据
- [`builder/recovery_host.py`](../../builder/recovery_host.py) — 宿主机侧 `AdbTransport` 封装，对应 device 端各子命令

## 易踩坑

- 在 normal 模式下调用 `flash`/`backup` 会被拒绝，这是设计行为，不是 bug
- 事实源为构建时冻结的 `/etc/flange/recovery-config.json`，脚本不扫描 `/proc`；分区布局变动须重建 recovery rootfs
