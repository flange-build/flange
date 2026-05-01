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
updated: 2026-04-30
---

## TL;DR

`builder/recovery_host.py` 实现宿主机端 `flange recovery` 命令组；通过 `Transport` 抽象与设备上的 `recoveryctl` 通信，编排 enter/list/flash/backup/shell/reboot 六个子命令。flash/backup 数据面走 `adb forward + 127.0.0.1 TCP socket`，控制面走 `adb shell` stdout 单行 ASCII 控制行。

## 关键设计要点

- **Transport 抽象**：`Transport` ABC 定义 `wait`、`push`、`pull`、`shell`、`shell_streaming`、`forward(remote_port) -> local_port`、`forward_remove(local_port)`、`interactive_shell` 接口；`AdbTransport` 封装 `adb` 子进程并解析返回码（含 stdout 中 `__flange_rc__=` 标记的提取与剥离）
- **设备模式查询**：`query_device_mode` 轮询 `recoveryctl mode`，最多 8 次重试；`require_recovery_mode` 在非 recovery 模式时抛出异常
- **enter**：`cmd_enter` 发 `boot-once` 重启，`wait(timeout=90)` 等待 ADB 重连，再确认模式
- **flash**：本地计算 size/SHA256 → `shell_streaming("recoveryctl flash --size N --sha256 H --listen tcp:0")` → 解析 stdout 控制行 `PORT=` / `READY` → `forward(<remote>)` 取本地端口 L → `connect 127.0.0.1:L` → 4MiB chunk 写 socket（host 自己跟踪 sent bytes 显示百分比+速率） → 等 `STATUS:OK` / `STATUS:FAIL:<reason>` + `__flange_rc__` → `forward_remove(L)`；protected 分区要求输入 `YES` 并默认读回校验（`--verify-readback`）
- **backup**：本地写 `<output>.partial` → `shell_streaming("recoveryctl backup --listen tcp:0 [--compress zstd]")` → 同样的 PORT/READY/forward/connect 流程 → 从 socket 读到 EOF → 等 `STATUS:OK` → `os.replace(<output>.partial, <output>)` 原子改名；任何失败路径下清理 `.partial`，原 `<output>` 不被破坏
- **`run_listener_session(transport, *, shell_args, on_data, partition_label, progress_cb)`**：flash 与 backup 共用的编排 helper，封装 shell_streaming → 解析 PORT/READY/PROGRESS/STATUS:OK/STATUS:FAIL/__flange_rc__ 控制行 → `adb forward` → `connect 127.0.0.1` → 调 `on_data(sock)` 让调用方读写 socket → 等 STATUS+rc → 清理 forward
- **失败措辞按边界划分**：`run_listener_session` 在 socket 是否 connect 上做边界，accept 之前的失败报"目标分区未改动"，accept 之后的失败报"可能已部分写入"
- **不依赖 `adb exec:` / `shell:v2`**：flange 选用的 adbd（android-tools-4.2.2）只支持 `backup: framebuffer: jdwp: reboot: remount: restore: root: shell: sync: tcp:`；数据面强制走 forward+TCP 路径
- **错误路径**：`shell` 返回非零抛 `HostRecoveryError`；`main` 捕获后彩色打印并 `sys.exit(1)`

## 关键代码位置

- [`builder/recovery_host.py:Transport`](../../builder/recovery_host.py) — Transport ABC，含 8 个接口
- [`builder/recovery_host.py:AdbTransport`](../../builder/recovery_host.py) — ADB 实现，含 `forward` / `forward_remove` / `shell_streaming` / `__flange_rc__` 解析
- [`builder/recovery_host.py:run_listener_session`](../../builder/recovery_host.py) — flash/backup 共用编排 helper，L382
- [`builder/recovery_host.py:cmd_flash`](../../builder/recovery_host.py) — flash 子命令，L496
- [`builder/recovery_host.py:cmd_backup`](../../builder/recovery_host.py) — backup 子命令，L591
- [`builder/recovery_host.py:cmd_enter`](../../builder/recovery_host.py) — enter 子命令，L294
- [`builder/recovery_host.py:query_device_mode`](../../builder/recovery_host.py) — 模式查询，L246
- [`builder/recovery_host.py:build_argparser`](../../builder/recovery_host.py) — 命令行解析，L691
