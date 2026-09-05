---
title: app 打包系统
type: component
status: stable
sources:
  - builder/app.py
  - builder/app_build.py
  - builder/app_resolver.py
  - builder/app_spec.py
  - builder/app_model.py
  - builder/toolchain.py
  - builder/deb.py
  - docs/app-architecture.md
updated: 2026-09-05
---

# App 构建与打包

`app.yaml` → 严格 AppSpec → AppResolver 依赖闭包 → 原生编译与安装树 → deb 与 ArtifactManifest。
第一次创建 App 从[创建流程](../workflows/scaffold-新建-app-流程.md)进入；
完整字段、安装规则与维护接口由[App 架构](../../docs/app-architecture.md)维护。

| 层 | 责任 |
| --- | --- |
| `app_spec.py` | 解析 App 类型、构建/安装声明、运行入口和动作，拒绝重复键与未知字段 |
| `app_resolver.py` | 统一名称/路径来源和递归依赖，拒绝缺失、循环及同名不同源 |
| `app_build.py` / `toolchain.py` | 目标工具链、隔离工作区、原生适配、缓存和原子发布 |
| `app.py` / `deb.py` | 安装文件收集、ELF 架构检查、Debian 打包 |
| `app_model.py` | AppBuildReport，连接构建、rootfs 安装及设备部署 |

三类依赖作用不同：`build.apt_packages` 在容器准备开发包，`build.deps` 建立 App 构建闭包，
顶层 `depends` 写入 deb 运行依赖。lib 可发布运行时和开发包；依赖安装树为下游提供编译前缀，
但它不等于完整系统 sysroot（目标根目录）。

产物位于当前工作区 `<target_dir>/apps/<resource-id>/` 的 `install/`、`artifacts/`
及清单中。系统 `app` 组件还发布 `apps/build-report.json`；rootfs/recovery 安装各自报告选出的集合，
不扫描整个目录里的历史 deb。custom/build action 在 Docker 的隔离副本执行，不污染原始源码。

资源生命周期包括 `create/list/plan/build/deploy/run/test/debug/log`，
详见[仓库外 App 开发](../workflows/out-of-tree-app-构建.md)。
