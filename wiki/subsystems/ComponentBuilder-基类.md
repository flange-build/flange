---
title: ComponentBuilder 基类
type: subsystem
status: stable
sources:
  - builder/base.py
  - builder/source.py
  - builder/engine.py
  - docs/build-system-design.md
  - docs/extension-guide.md
updated: 2026-09-05
---

# ComponentBuilder 基类

[`builder/base.py`](../../builder/base.py) 提供平台组件的模板方法：
`configure(src_dir, config)` → `compile(src_dir, config)` → `collect(src_dir, config)`。
`collect()` 返回本次实际产物路径；由引擎负责验证和发布，不能自行把“成功标记”当作缓存。

当前系统入口通过 `execute(plan)` 消费 TaskPlan 声明中的配置，
引擎注入工作区上下文、日志和当前 App 报告。
默认 `build()` 先从 SourceManager 获取目标独立工作树，再重置、应用补丁并执行三个阶段。
无源码组件可重写构建步骤，但仍须遵循输入、工作区与产物契约。

补丁按平台后板级、各目录文件名顺序应用；组件 `exclude_patches` 可排除不适用补丁。
本地 `sources.<name>.local_path` 会先复制隔离，保留调用者当前内容并跳过自动重置和重复补丁。
编译、patch 与 reset 都不能回写用户原始源码或共享下载仓库。

构建命令委托给 [DockerRunner](Docker-执行封装.md)。
`work_dir()` 在 `<build_root>/work/<target.key>/` 下创建当前执行的暂存区，
不同目标使用各自目录。

扩展已有平台配方见[扩展指南](../../docs/extension-guide.md)，缓存和发布边界见
[构建系统设计](../../docs/build-system-design.md)。
