---
title: FINAL_CONFIG
type: concept
status: stable
sources:
  - ProjectSpec.md#62-配置体系
  - builder/config/registry.py
  - builder/config/query.py
  - builder/config/loader.py
related:
  - "[[三层继承]]"
  - "[[condition-markers]]"
  - "[[product-variant]]"
  - "[[配置子系统]]"
updated: 2026-04-26
---

## TL;DR

扁平 dict，由三层继承合并 + condition-markers 展开后产出，作为构建系统全局事实源传递给所有 ComponentBuilder。

## 关键设计要点

- **产生路径**：`resolve_config(board, product, variant)` → 三层 deep_merge → resolve_conditions → normalize_app_sources → FINAL_CONFIG dict
- **主要字段约定**：
  - `arch` / `platform` / `soc` / `board` — 平台标识
  - `kernel` / `bootloader` / `rootfs` / `recovery` — 各组件子树
  - `partitions.entries` — 分区表条目列表
  - `flash_tool` — 刷写工具标识（rockchip / allwinner 等）
  - `product` / `variant` — 当前选择（由 resolve_conditions 写入）
- **不可变语义**：resolve_config 返回新 dict，不修改任何输入；下游模块只读不写
- **BuildCache 消费**：`BuildCache(config)` 接收 FINAL_CONFIG，作为所有哈希计算的基础
- **loader.py 缺失**：`sources` 中列出的 `builder/config/loader.py` 实际不存在（功能已并入 registry.py）

## 关键代码位置

- [`builder/config/registry.py:resolve_config`](../../builder/config/registry.py) — 产生入口，L151
- [`builder/config/merge.py:resolve_conditions`](../../builder/config/merge.py) — 条件展开，L68
- [`builder/cache.py:BuildCache.__init__`](../../builder/cache.py) — 消费 config，L62

## 延伸阅读

- [ProjectSpec §6.2](../../ProjectSpec.md#62-配置体系)
- [[三层继承]]
- [[condition-markers]]
- [[配置子系统]]
