---
title: product-variant
type: concept
status: stable
sources:
  - ProjectSpec.md#11-构建系统约定
  - builder/config/query.py
related:
  - "[[FINAL_CONFIG]]"
  - "[[condition-markers]]"
updated: 2026-04-26
---

## TL;DR

`lunch <board>-<product>-<variant>` 选择构建目标，持久化到 `.build/state.json`，后续 `flange build/flash` 命令均以此为准。

## 关键设计要点

- **product**：对应同一硬件板的不同软件套件或使用场景，如 `default`、`smart-display`；在 board `config.jsonnet` 的 `products` 列表中声明
- **variant**：通常为 `release` / `debug`；通过 Jsonnet `if std.extVar('variant')` 选择差异；在 `variants` 列表中声明
- **目标格式 `<board>-<product>-<variant>`**：板名可含连字符（如 `radxa-zero3w`），`parse_target()` 用最长板名优先匹配策略解析
- **有效目标枚举**：`get_valid_targets()` 遍历所有 board × product × variant 组合，供 `lunch` tab 补全
- **产物路径隔离**：`.build/target/<board>/<product>/<variant>/` — 不同 product/variant 产物互不覆盖

## 关键代码位置

- [`builder/config/query.py:parse_target`](../../builder/config/query.py) — 目标字符串解析，L49
- [`builder/config/query.py:get_valid_targets`](../../builder/config/query.py) — 有效目标枚举，L26

## 延伸阅读

- [ProjectSpec §6.2](../../ProjectSpec.md#62-配置体系)
- [[FINAL_CONFIG]]
- [[condition-markers]]
