---
title: rootfs 两阶段缓存
type: concept
status: stable
sources:
  - builder/platforms/rockchip/rootfs.py
  - builder/cache.py
related:
  - "[[rootfs 构建器]]"
  - "[[内容哈希与增量构建]]"
  - "[[缓存系统]]"
updated: 2026-05-04
---

## TL;DR

rootfs 构建分 base（apt install）和 customize（overlay + deb）两阶段独立缓存，改 overlay 跳过耗时 5-15 分钟的 apt 阶段。

## 关键设计要点

- **Phase 1 base 哈希输入**：`rootfs.url`（ubuntu-base tarball URL）+ `sorted(rootfs.packages)` + `arch` — 包集合不变时复用 `base.tar.gz` 快照
- **Phase 2 customize 哈希输入**：base_hash + overlay 目录递归哈希 + custom_packages + root_password + extra_firmware + extra_debs + partitions — 任一变化只跳过 Phase 1 重跑 Phase 2
- **跨 product/variant 共享**：相同 packages → 相同 base_hash → 共享同一份 `base.tar.gz`；不同 product/variant 的 rootfs 可复用同一 base 快照
- **recovery 也复用**：recovery 构建的 Phase 1 复用 `rootfs.url` 同一 tarball 来源，减少重复下载
- **分阶段接口**：`compute_phase_hash("rootfs","base")` / `is_phase_up_to_date` / `store_phase` — 在 `cache.py` 中实现

## 关键代码位置

- [`builder/cache.py:BuildCache._compute_rootfs_base_hash`](../../builder/cache.py) — Phase 1 哈希，L205
- [`builder/cache.py:BuildCache._mix_rootfs_customize`](../../builder/cache.py) — Phase 2 哈希，L218
- [`builder/cache.py:BuildCache.compute_phase_hash`](../../builder/cache.py) — 分阶段接口，L183

## 延伸阅读

- [[内容哈希与增量构建]]
- [[rootfs 构建器]]
- [[缓存系统]]
