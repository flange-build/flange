---
title: external_apps 装载
type: workflow
status: stable
sources:
  - builder/workspace.py
  - builder/app_resolver.py
  - builder/source.py
  - builder/config/apps.py
  - docs/app-architecture.md
updated: 2026-09-05
---

# App 来源与 external_apps

名称、路径和当前目录入口统一进入 AppResolver（应用解析器）。
新建独立工程时先读[仓库外 App 开发](out-of-tree-app-构建.md)，
完整查找契约见[App 架构](../../docs/app-architecture.md)。

当前解析顺序为：显式路径 → 工作区 `[apps]` 注册 → 调用位置已有同名目录 →
工作区 `app_dirs` 搜索 → 工具来源。工具来源仍包括 `components/app/`、
系统配置 `external_apps` 和 `external_app_dirs`，不是整个生命周期只有旧三层查找。

```toml
# flange.toml 中路径相对本文件
schema_version = 1
tool_root = "/path/to/flange"
build_dir = ".build"
app_dirs = ["apps"]

[apps]
shared-lib = "../shared-library"
```

路径只在声明位置解析一次；App 的相对 `build.deps` 则相对当前 App 目录。
多个 `app_dirs` 命中同名 App 时要求显式注册；同一依赖闭包含同名不同源、缺失或循环依赖时构建失败。
不要用旧 first-match（找到即取）概括工作区与整个依赖闭包的行为。

```bash
flange app list
flange app plan ./apps/demo
```

`plan` 展开完整依赖但不下载尚未准备的 Git 来源。
实际 build 准备远端版本或本地隔离副本后计算输入身份；修改源码能触发缓存失效，
不再只凭 `app.yaml` 或手动更新 `ref` 判断。
