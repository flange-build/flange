---
title: FINAL_CONFIG
type: concept
status: stable
sources:
  - ProjectSpec.md#62-配置体系
  - builder/config/jsonnet.py
  - builder/config/registry.py
  - builder/config/validate.py
related:
  - "[[三层继承]]"
  - "[[condition-markers]]"
  - "[[product-variant]]"
  - "[[配置子系统]]"
updated: 2026-08-26
---

## TL;DR

FINAL_CONFIG 是 Jsonnet 求值、包集合展开和 canonical 校验后的普通 JSON object，也是所有 ComponentBuilder 的配置事实源。

## 关键设计要点

- **产生路径**：`resolve_config(board, product, variant)` → Jsonnet 固定层级求值 → package/App 规范化 → `validate_config()`。
- **架构**：唯一使用 `architecture.{userspace,kernel,bootloader}`。
- **Kconfig**：`kernel.config` 与 `bootloader.config` 使用 `CONFIG_* → y/m/n/token`；`defconfig` 只放 make target/fragment 名称。
- **设备树**：唯一使用 `kernel.device_tree.{directory,name,build_overlays}`。
- **源码**：描述符位于 `sources.<name>`，组件只通过 `source.{name,subpath}` 引用。
- **运行期 overlay**：统一位于 `boot.overlays.{intree,vendor,board,package,enabled}`。
- **下载**：统一使用 `{url,sha256,filename}` descriptor。
- `product` / `variant` 只出现在顶层，下游不得解释条件键或 alias。

## 关键代码位置

- [`builder/config/registry.py:resolve_config`](../../builder/config/registry.py) — 产生入口
- [`builder/config/jsonnet.py:JsonnetConfigLoader`](../../builder/config/jsonnet.py) — 求值与规范化
- [`builder/config/validate.py:validate_canonical_config`](../../builder/config/validate.py) — canonical 契约
- [`builder/cache.py:BuildCache`](../../builder/cache.py) — 配置与 Jsonnet 依赖哈希消费者
