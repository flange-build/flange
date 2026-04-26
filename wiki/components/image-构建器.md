---
title: image 构建器
type: component
status: stable
sources:
  - builder/platforms/rockchip/image.py
  - builder/flash.py
  - builder/partition/rockchip.py
related:
  - "[[ComponentBuilder 基类]]"
  - "[[分区表系统]]"
  - "[[flash-config.json]]"
  - "[[lunch-build-flash 流程]]"
updated: 2026-04-26
---

## TL;DR

将 bootloader/kernel/rootfs/recovery 产物按分区布局组装为 GPT 整盘 `raw.img`；无需克隆源码，直接从 `target_dir` 取各组件产物 dd 进镜像。

## 关键设计要点

- **跳过源码阶段**：`build()` 直接调 `compile(None, config)`，跳过 source.ensure/reset/patch
- **分区布局**：`_resolve_entries`（L108）将 hex 字符串 offset/size 转 sectors；`_total_sectors`（L123）加 2048 sectors GPT 尾部保留
- **raw 分区**：`type=="raw"`（如 idbloader）不进 GPT 表，仅 dd；GPT 分区按顺序 `parted mkpart`
- **分区顺序**（commit fa745b0）：idbloader → uboot → boot → recovery → rootfs；recovery 在 rootfs 之前
- **产物映射**：`PARTITION_IMAGES`（L31）字典映射分区名→路径；产物不存在则跳过（recovery 未启用时安全）
- **rootfs PARTUUID**：固定 `"614e0000-0000-4000-8000-000000000000"`，供 kernel cmdline 引用
- **collect**：`{"image": raw_img}`；`BuildEngine._generate_flash_config` 注入 flash-config.json

## 关键代码位置

- [`builder/platforms/rockchip/image.py:RockchipImageBuilder`](../../builder/platforms/rockchip/image.py) — 主类，L25
- [`builder/platforms/rockchip/image.py:compile`](../../builder/platforms/rockchip/image.py) — GPT + dd，L49
- [`builder/platforms/rockchip/image.py:PARTITION_IMAGES`](../../builder/platforms/rockchip/image.py) — 产物路径表，L31

## 易踩坑

- `remaining` 分区默认 4 GB，超出 eMMC 容量的镜像刷写时被截断
- `parted`/`sfdisk` 须在 Docker 内执行；`self.docker.run` 已封装，勿在宿主机直接调
