---
title: out-of-tree app 构建
type: workflow
status: stable
sources:
  - builder/workspace.py
  - builder/app_resolver.py
  - builder/app_build.py
  - builder/dev.py
  - docs/development-guide.md
  - docs/app-architecture.md
  - docs/first-steps.md
updated: 2026-09-05
---

# 在仓库外开发 App

out-of-tree（源码树外）开发把自己的项目与 flange 工具 checkout 分开。
先完成[初学指南](../../docs/first-steps.md)的安装和 Docker 准备，
再按[开发指南](../../docs/development-guide.md)建立自己的工作区。

```bash
flange init ~/workspace/my-product --tool-root /path/to/flange
cd ~/workspace/my-product
flange target select radxa-zero3w-default-debug
flange app create demo --dir apps --type exec --build-system cmake
cd apps/demo
flange app plan
flange app build
```

将 `/path/to/flange` 换成实际工具根。`create --dir` 指工程父目录；省略则使用调用者目录。
其他资源命令可接名称或含 `app.yaml` 的路径；省略时使用调用者目录。
相对依赖以声明它的 App 为基准，工作区注册与查找规则见[外部 App 装载](external_apps-装载.md)。

源码先复制到目标独立工作区，原生构建系统完成编译与安装收集后，
发布到 `<build_root>/target/<board>/<product>/<variant>/apps/<resource-id>/`。
这里包含 `install/`、`artifacts/`、`resource.json`、`manifest.json`；debug 目标另有匹配源码。
AppBuildReport 记录请求根及完整依赖结果，部署不会扫描目录猜测当前 deb。

设备可见且满足 ADB、权限和安装依赖后，在 App 目录执行：

```bash
flange app deploy --serial SERIAL --no-build
flange app run --serial SERIAL --no-build -- --example-argument
flange app test --serial SERIAL --no-build
flange app debug --serial SERIAL --no-build
```

`--no-build` 仍验证已有成功报告与实际产物。多设备时必须明确 serial。
默认 debug 要求 debug target；service 日志使用 `flange app log`。
测试结果与调试会话关联本次目标、设备和产物，完整边界见[开发指南](../../docs/development-guide.md)。

App 与 Package 的 `actions` 接受 `build/deploy/run/debug/log/test` 的非空 argv（参数向量）列表。
build action 在 Docker 的隔离副本执行，之后仍需完成安装收集、架构和清单验证；
其他显式动作在宿主执行。工作目录、环境变量及覆盖语义统一见[App 架构](../../docs/app-architecture.md)。

旧 `flange build app <name>`、`flange push app`、`flange run app`、`flange create app`
入口已移除。系统 `flange build app` 仍表示构建当前系统配置选择的 App 集合，
单 App 开发使用 `flange app build <name-or-path>`。
