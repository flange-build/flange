---
title: condition-markers
type: concept
status: stable
sources:
  - ProjectSpec.md#62-配置体系
  - builder/config/merge.py
related:
  - "[[三层继承]]"
  - "[[FINAL_CONFIG]]"
  - "[[product-variant]]"
updated: 2026-04-26
---

## TL;DR

配置 dict 中的特殊键语法，用于在同一份配置中表达"仅当 product/variant 匹配时生效"的差异化内容，由 `resolve_conditions()` 在产出 FINAL_CONFIG 前展开。

## 关键设计要点

- **`+key` 追加语义**：无条件将 value 追加到 base_key 对应的 list；若 base_key 是 dict 则深度合并追加。例：`+packages: ["gdb"]` 无条件在 packages 后追加
- **`key:condition` 条件覆盖**：仅当 `condition` 等于当前 product 或 variant 时才覆盖 base_key。例：`packages:smart-display` 仅 product=smart-display 时替换 packages
- **`+key:condition` 条件追加**：两者结合 — 仅匹配时追加。例：`+packages:debug` 仅 variant=debug 时追加调试包
- **展开顺序**：普通键 → 无条件 +key → 匹配的条件键（后者可覆盖前者）
- **不匹配的条件键被丢弃**：不匹配的 `key:other-product` 在最终 dict 中不出现

## 关键代码位置

- [`builder/config/merge.py:resolve_conditions`](../../builder/config/merge.py) — 展开逻辑，L68
- [`builder/config/merge.py:deep_merge`](../../builder/config/merge.py) — `+key` 追加处理，L11

## 易踩坑点

- `+key` 和 `key:condition` 在同一 dict 中可以共存，但 `+key` 无条件追加会在条件覆盖之前执行，条件覆盖结果会替换掉追加后的列表

## 延伸阅读

- [ProjectSpec §6.2](../../ProjectSpec.md#62-配置体系)
- [[三层继承]]
- [[FINAL_CONFIG]]
- [[product-variant]]
