---
title: recovery 构建器
type: component
status: stable
sources:
  - builder/recovery.py
  - openspec/specs/recovery-boot/spec.md
  - openspec/specs/recovery-usb-flash/spec.md
related:
  - "[[recovery 系统]]"
  - "[[ComponentBuilder 基类]]"
  - "[[rootfs 构建器]]"
  - "[[recoveryctl]]"
updated: 2026-04-26
---

## TL;DR

独立 ext4 镜像（label=recovery）；与 normal rootfs 共享 ubuntu-base tarball 但包集合独立；必含 `recoveryctl` + `adbd`；4 阶段：Phase1 apt → Phase2 deb+modules+overlay → Phase3 fstab+config → Phase4 mke2fs。

## 关键设计要点

- **与 rootfs 差异**：读 `config["recovery"]`；包列表精简；额外写 `/etc/flange/recovery-config.json`；recovery 自身 protected
- **recovery-config.json**（`build_recovery_config`，L34）：纯函数；schema v1：board/product/variant/transport + partitions；`type=="raw"` 或 `protected_partitions` 的分区标 protected
- **Phase 1**（`_build_phase1`，L138）：ubuntu-base + apt；base cache 同 rootfs
- **Phase 2**（`_build_phase2`，L172）：dpkg deb（含 recoveryctl/adbd）；kernel modules；recovery overlay
- **Phase 3**：fstab（L259）+ recovery-config.json（L286）
- **Phase 4**：`mke2fs -d` 从目录制 ext4，无 loop device
- **engine**：`recovery.enabled=false` 时 `_component_disabled` 跳过

## 关键代码位置

- [`builder/recovery.py:RecoveryBuilder`](../../builder/recovery.py) — 主类，L88
- [`builder/recovery.py:build_recovery_config`](../../builder/recovery.py) — 生成 config，L34
- [`builder/recovery.py:_build_phase2`](../../builder/recovery.py) — deb+modules+overlay，L172
- [`builder/recovery.py:_install_recovery_config`](../../builder/recovery.py) — 写入配置，L286

## 易踩坑

- recovery 分区自身始终 protected（`build_recovery_config` 硬编码），设备端拒绝自写
- `mke2fs -d` 需 e2fsprogs 新版本；Docker 镜像已固定，宿主机勿直接调
