---
title: 构建引擎 BuildEngine
type: subsystem
status: stable
sources:
  - builder/engine.py
related:
  - "[[ComponentBuilder 基类]]"
  - "[[缓存系统]]"
  - "[[内容哈希与增量构建]]"
  - "[[输出系统 BuildOutput]]"
updated: 2026-04-26
---

## TL;DR

`BuildEngine` 是从 `lunch` 选好配置到刷写 config 生成的中央编排器；负责拓扑排序依赖、按序实例化组件构建器、查询缓存跳过重复构建、汇总产物并生成 flash-config.json。

## 关键设计要点

- **拓扑排序**：`_topo_sort` 使用 DFS 对组件依赖图排序，保证 bootloader/kernel 先于 rootfs/image 构建
- **组件实例化**：`_get_builder` 按组件名动态选取对应 ComponentBuilder 子类（kernel/bootloader/rootfs/recovery/image/app）
- **增量跳过**：`_build_components` 在构建每个组件前调用 `BuildCache.is_up_to_date`，命中则跳过并取缓存产物
- **组件禁用**：`_component_disabled` 读取 config 中 `disabled: true` 字段；recovery 未开启时跳过 recovery 构建
- **产物汇总**：`_collect_artifacts` 将各组件 `collect()` 返回的路径映射统一存入 `_artifact_names`
- **flash-config 生成**：`_generate_flash_config` 以 FINAL_CONFIG 中的分区表为骨架，注入产物路径，输出 `.build/flash-config.json`
- **BuildOutput 注入**：`BuildEngine.__init__` 创建 `BuildOutput` 实例并下传给所有子构建器，统一格式化输出

## 关键代码位置

- [`builder/engine.py:BuildEngine`](../../builder/engine.py) — 主类，L38
- [`builder/engine.py:BuildEngine.build`](../../builder/engine.py) — 入口，L56
- [`builder/engine.py:BuildEngine._build_components`](../../builder/engine.py) — 增量调度，L73
- [`builder/engine.py:BuildEngine._generate_flash_config`](../../builder/engine.py) — 产物配置，L158
- [`builder/engine.py:_topo_sort`](../../builder/engine.py) — 依赖排序，L14
