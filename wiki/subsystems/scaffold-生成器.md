---
title: scaffold 生成器
type: subsystem
status: stable
sources:
  - builder/scaffold.py
  - builder/templates/
  - builder/cli.py
  - docs/app-architecture.md
  - builder/templates
  - docs/extension-guide.md
updated: 2026-09-05
---

# scaffold 生成器

[`builder/scaffold.py`](../../builder/scaffold.py) 根据类型、原生构建系统、名称和目标架构渲染
[`builder/templates/`](../../builder/templates/) 中的工程模板。
公共入口为 `flange app create` 和 `flange package create`，`--dir` 表示父目录。
第一条创建路径见[创建第一个 App](../workflows/scaffold-新建-app-流程.md)。

维护模板时必须同时看生成的 `app.yaml`、原生编译文件与安装规则：
当前 CMake/Meson/Make 适配器会执行安装阶段，并把安装树作为准确产物收集入口。
过去“模板 install 是死代码、必须手工拷到 bin/”的故障已由统一安装收集流程替代，
不再是使用建议。

模板可生成 exec（可执行程序）、service（服务）、lib（库）、test（测试）或 AMP 固件等类型；
具体合法组合由 CLI 与生成器校验。模板支持与任意手写 AppSpec 能力并非同一集合，
不能只添加一个模板目录就宣称支持新的构建系统。

新增模板或适配器时依照[扩展指南](../../docs/extension-guide.md)验证生成工程的
解析、计划、容器真实构建、安装树与运行入口；字段语义见[App 架构](../../docs/app-architecture.md)。
