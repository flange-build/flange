---
title: flange-rootfs-grow
type: app
status: stable
sources:
  - components/app/flange-rootfs-grow/app.yaml
  - components/app/flange-rootfs-grow/scripts/flange-rootfs-grow
  - components/app/flange-rootfs-grow/systemd/flange-rootfs-grow.service
related:
  - "[[rootfs 构建器]]"
  - "[[app 打包系统]]"
updated: 2026-05-03
---

## TL;DR

首次启动时自动扩展 rootfs 分区至磁盘剩余空间并 grow ext4。`ConditionPathExists=!/var/lib/flange/rootfs-grown` 保证只执行一次。

## 关键设计要点

- **分区布局**：rootfs 镜像按 `image_size`（如 `1536M`）构建，分区声明 `size: remaining` 占满磁盘
- **扩展流程**：`findmnt` → `lsblk` 定位分区 → `sgdisk -e` 扩 GPT → `growpart` 扩分区 → `partprobe` → `resize2fs` → 写 marker `/var/lib/flange/rootfs-grown`
- **幂等**：`growpart` 返回 `NOCHANGE:` 时仍继续 `resize2fs`（分区已扩但 fs 未 grow 的场景）

## 关键代码位置

- [`components/app/flange-rootfs-grow/scripts/flange-rootfs-grow`](../../components/app/flange-rootfs-grow/scripts/flange-rootfs-grow) — 扩展脚本
- [`components/app/flange-rootfs-grow/systemd/flange-rootfs-grow.service`](../../components/app/flange-rootfs-grow/systemd/flange-rootfs-grow.service) — systemd unit
