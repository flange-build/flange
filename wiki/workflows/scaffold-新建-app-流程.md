---
title: scaffold 新建 app 流程
type: workflow
status: stable
sources:
  - builder/scaffold.py
  - builder/templates/
related:
  - "[[scaffold 生成器]]"
  - "[[app 打包系统]]"
  - "[[external_apps 装载]]"
updated: 2026-04-26
---

## TL;DR

`flange create app <name> --type <type> --build-system <bs>` → 从模板生成骨架 → 编辑 `app.yaml` + 业务代码 → `flange build`

## type × build-system 模板矩阵

基于 `builder/templates/` 实际目录：

| type | 支持的 build-system |
|---|---|
| `exec` | cmake / make / meson / swift |
| `service` | cmake / make / meson / swift（+ conf / systemd 辅助模板） |
| `lib` | cmake / make / meson |
| `test` | none |

## 生成位置

- **默认位置**：`components/app/<name>/`（框架自动扫描到，无需注册）
- **外部目录**：指定 `--output-dir` 时生成于仓库外；scaffold 会提示注册指引（需在 `FINAL_CONFIG` 的 `external_apps` 或 `external_app_dirs` 中添加）。

## 流程步骤

1. **运行 scaffold**：`flange create app my-daemon --type service --build-system cmake` → 生成 `components/app/my-daemon/app.yaml`、`CMakeLists.txt`、`src/main.c`、`my-daemon.service`。

2. **编辑 app.yaml**：填写 `description`、`depends`、`install`、`systemd_service`；`type`/`build_system` 已预填。

3. **构建验证**：`flange build rootfs` — [[app 打包系统]] 的 `AppBuilder` 自动发现并构建。

scaffold 只负责生成文件，构建流程（编译 → deb → rootfs install）由 [[app 打包系统]] 承担。
