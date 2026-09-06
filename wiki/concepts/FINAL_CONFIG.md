---
title: FINAL_CONFIG
type: concept
status: stable
sources:
  - ProjectSpec.md#62-配置体系
  - builder/config/jsonnet.py
  - builder/config/registry.py
  - builder/config/validate.py
  - builder/config/schema.py
  - builder/component_plan.py
  - docs/build-system-design.md
  - docs/extension-guide.md
related:
  - "[[三层继承]]"
  - "[[condition-markers]]"
  - "[[product-variant]]"
  - "[[配置子系统]]"
updated: 2026-09-05
---

## TL;DR

FINAL_CONFIG（最终配置）是 Jsonnet 求值、包集合展开和 canonical（规范化）校验后的配置事实源。
当前 Python 求值结果以 `ResolvedConfig` 携带配置与依赖/hash 元数据；执行者消费已求值字段，不再解释条件。
完整输入边界见[构建系统设计](../../docs/build-system-design.md)，新增字段见[扩展指南](../../docs/extension-guide.md)。

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
- [`builder/config/schema.py`](../../builder/config/schema.py) 与 [`validate.py`](../../builder/config/validate.py) — 闭合字段、严格类型与跨字段语义
- [`builder/component_plan.py`](../../builder/component_plan.py) — 声明配置、Jsonnet 依赖及组件输入
