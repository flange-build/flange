---
title: 路径锚点 paths
type: subsystem
status: stable
sources:
  - builder/paths.py
  - builder/workspace.py
  - docs/build-system-design.md
updated: 2026-09-05
---

# 路径锚点与工作区上下文

[`builder/paths.py`](../../builder/paths.py) 集中定义 `COMPONENTS_DIRNAME`、`BUILD_DIRNAME`
以及工具仓库默认 `PROJECT_ROOT`、`COMPONENTS_ROOT`、`BUILD_ROOT`。
这些默认值不能替代外部工作区自己的路径。

运行期使用 [`builder/workspace.py`](../../builder/workspace.py) 的不可变 WorkspaceContext：

| 字段 | 归属 |
| --- | --- |
| `tool_root` / `components_root` | 工具代码、平台内容、模板与 Docker 配置 |
| `workspace_root` / `state_file` | `flange.toml` 与 `.flange/current_config` |
| `build_root` / `sources_dir` | 当前工作区的输出和下载存储 |
| `target` / `target_dir` | 结构化目标与该目标发布目录 |
| `invocation_dir` | 解释用户命令中的相对路径 |
| `apps` / `app_dirs` | 从工作区清单解析的外部 App 来源 |

清单内路径相对 `flange.toml` 所在目录解析一次；用户命令中的路径相对调用者目录解释。
把这些目录重新合成一个 `project_root` 会使外部工作区、缓存和部署互相污染。

`components_dir(root)` / `build_dir(root)` 仍用于计算默认目录及测试注入。
新代码应从调用链传入 context，避免硬编码工具 checkout 的 `.build`，也不依赖旧 `target` 软链接。
示例布局见[仓库三层结构](../concepts/仓库三层结构.md)，维护规则见
[构建系统设计](../../docs/build-system-design.md)。
