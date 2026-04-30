---
title: recoveryctl 协议
type: concept
status: stable
sources:
  - components/app/recoveryctl/bin/recoveryctl
  - builder/recovery_host.py
related:
  - "[[recoveryctl]]"
  - "[[recovery-host-CLI]]"
  - "[[recovery 系统]]"
updated: 2026-04-26
---

## TL;DR

设备端 CLI `recoveryctl`，由宿主机通过 ADB exec 调用；事实源为构建时冻结的 `/etc/flange/recovery-config.json`，不重新发现分区。

## 关键设计要点

- **子命令集**：`mode`（输出 normal/recovery）、`list`（分区清单+块设备状态）、`flash <part> --size <n> --sha256 <hash>`（stdin 流式写入）、`backup <part> <out>`（读取分区）、`recovery/loader/normal`（重启目标）、`reboot [target]`（兼容入口）
- **事实源**：`/etc/flange/recovery-config.json` — 由 `RecoveryBuilder` 在构建时冻结；`recoveryctl` 不重新扫描 `/proc`，保证与构建时分区布局一致
- **安全要求**：host 默认调用 `flash`，设备端在读取 stdin 前完成 preflight；写入时统计字节数并校验 stdin 数据 sha256，`--force` 写 protected 分区默认读回校验
- **模式守卫**：`flash`、`backup` 等危险操作先检查 `mode == recovery`，在 normal 模式下拒绝执行，防止从 ADB 误触
- **失败语义**：preflight 失败表示目标分区未改动；写入开始后若 stdin 提前结束、sha256 不匹配或 USB 断开，目标分区可能已部分写入，需要重新刷写或从备份恢复
- **宿主机编排**：`builder/recovery_host.py` 的 `AdbTransport` 封装 `adb exec-in / exec-out / shell / push / pull`；测试中可在 `tests/` 实现 `FakeTransport` 桩注入 `AdbTransport`
- **transport 扩展**：当前仅 ADB over USB；接口设计允许后续添加 USB DFU 等通道

## 关键代码位置

- [`components/app/recoveryctl/bin/recoveryctl`](../../components/app/recoveryctl/bin/recoveryctl) — 设备端实现，L1
- [`builder/recovery_host.py`](../../builder/recovery_host.py) — 宿主机 ADB 编排，L1

## 延伸阅读

- [[recovery 系统]]
- [[recovery-host-CLI]]
- [[recoveryctl]]
