---
title: 构建引擎 BuildEngine
type: subsystem
status: stable
sources:
  - builder/engine.py
  - builder/graph.py
  - builder/component_plan.py
  - builder/cache.py
  - builder/artifacts.py
  - docs/build-system-design.md
  - docs/maintenance-guide.md
updated: 2026-09-05
---

# 构建引擎 BuildEngine

`BuildEngine(config, context=...)` 将某个系统组件请求展开为依赖计划并执行。
它验证配置目标与 WorkspaceContext（工作区上下文）一致，不负责保存目标选择或解释 Shell 状态。

| 阶段 | 实现职责 |
| --- | --- |
| `plan()` / `explain()` | 创建 TaskPlan，展示输入、依赖、启用状态、输出与缓存原因；不隐式 fetch |
| `build()` | 持有当前目标锁，建立统一 BuildOutput 日志，执行所需依赖闭包 |
| `_build_components()` | 准备源码，比较输入与有效产物清单，执行或复用各组件 |
| `_get_builder()` | 从当前平台工厂取得策略；公共 overlay 组件走共享构建器 |
| `_collect_artifacts()` | 暂存并校验完整输出，再替换组件发布目录 |
| 完成 image | 调用 FlashConfigGenerator 生成当前目标的 `flash-config.json` |

App 有独立的依赖闭包和逐 App 缓存；系统 `app` 组件收集 AppBuildReport，
rootfs/recovery 只安装自己选择的准确集合。组件启用状态来自配置，不能由旧文件是否存在推断。

修改依赖、缓存或发布逻辑前读[构建系统设计](../../docs/build-system-design.md)与
[维护指南](../../docs/maintenance-guide.md)。源码入口：
[`engine.py`](../../builder/engine.py)、[`graph.py`](../../builder/graph.py)、
[`component_plan.py`](../../builder/component_plan.py)、[缓存系统](缓存系统.md)。
