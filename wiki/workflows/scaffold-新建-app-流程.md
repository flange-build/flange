---
title: scaffold 新建 app 流程
type: workflow
status: stable
sources:
  - builder/cli.py
  - builder/scaffold.py
  - builder/templates/
  - docs/development-guide.md
  - docs/app-architecture.md
  - docs/first-steps.md
  - docs/extension-guide.md
updated: 2026-09-05
---

# 创建第一个 App

阅读前提：已经完成[初学指南](../../docs/first-steps.md)的环境准备，并位于已初始化工作区。
scaffold（工程骨架生成器）只创建文件；构建、依赖与设备动作由统一 App 流程处理。

```bash
flange app create my-daemon --dir apps --type service --build-system cmake
flange app plan ./apps/my-daemon
flange app build ./apps/my-daemon
```

`--dir apps` 是父目录，结果为 `apps/my-daemon/`；省略 `--dir` 时在调用者目录创建。
架构默认跟随当前目标，未选目标时默认 aarch64，也可显式 `--arch`。
支持的类型、构建系统和组合以 `flange app create --help` 及生成器校验为准。

编辑生成的 `app.yaml`、源码和原生构建文件。
CMake/Meson/Make 使用安装阶段收集结果，不需要旧文档中的“强制把编译输出放进源码 bin/”绕行方案。
`build.deps` 声明 App 构建依赖，`build.apt_packages` 声明容器开发包，顶层 `depends` 声明 deb 运行依赖。

单独 `app build` 不会自动将该 App 加入系统镜像。需要随 rootfs 发布时，
按[扩展指南](../../docs/extension-guide.md)将它加入系统选择的 App/Package 集合。
完整安装和元数据契约见[App 架构](../../docs/app-architecture.md)。
