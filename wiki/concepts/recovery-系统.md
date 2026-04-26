---
title: recovery 系统
type: concept
status: stable
sources:
  - ProjectSpec.md#24-usb-线刷-recovery
  - docs/recovery.md
  - builder/recovery.py
  - openspec/specs/recovery-boot/spec.md
  - openspec/specs/recovery-usb-flash/spec.md
related:
  - "[[boot-once 启动切换]]"
  - "[[双 extlinux 配置]]"
  - "[[recoveryctl 协议]]"
  - "[[recoveryctl]]"
  - "[[recovery 在线刷写流程]]"
  - "[[recovery 构建器]]"
updated: 2026-04-26
---

## TL;DR

独立 ext4 分区（label=recovery）+ 独立 rootfs；normal 损坏时仍能启动维护，通过 USB ADB 执行分区级在线刷写。

## 关键设计要点

- **独立分区与 rootfs**：recovery 是独立 ext4 分区，与 normal rootfs 不共享运行时状态；normal 损坏时仍能启动
- **双 extlinux + boot-once**：boot 分区生成 `extlinux.conf`（normal）和 `recovery.conf`（recovery）；进入 recovery 通过 `reboot("recovery")` 触发 U-Boot one-shot 切换
- **ADB transport**：`flange recovery enter/list/flash/backup/shell/reboot` 宿主机命令通过 ADB 编排设备端 `recoveryctl`
- **安全策略**：bootloader（raw 类型）与 recovery 分区本身默认 protected；强制写入须宿主机输入 `YES` 且 device 端要求 `--sha256` 校验
- **构建流程**：4 阶段 — Phase1（ubuntu-base + apt）→ Phase2（deb + kernel modules + overlay）→ Phase3（fstab + recovery-config.json）→ Phase4（mke2fs 打包）
- **不属于范围**：OTA / A/B 切换 / 网络烧录 / recovery 自升级

## 关键代码位置

- [`builder/recovery.py:RecoveryBuilder`](../../builder/recovery.py) — 构建器，L88
- [`builder/recovery.py:build_recovery_config`](../../builder/recovery.py) — 生成 recovery-config.json，L34

## 延伸阅读

- [ProjectSpec §2.4](../../ProjectSpec.md#24-usb-线刷-recovery)
- [docs/recovery.md](../../docs/recovery.md)
- [[boot-once 启动切换]]
- [[recoveryctl 协议]]
