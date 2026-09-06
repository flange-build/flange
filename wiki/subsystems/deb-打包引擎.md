---
title: deb 打包引擎
type: subsystem
status: stable
sources:
  - builder/deb.py
  - builder/app_build.py
related:
  - "[[app 打包系统]]"
  - "[[scaffold 生成器]]"
updated: 2026-09-05
---

## TL;DR

`builder/deb.py` 提供纯 Python `.deb`（Debian 软件包）打包能力（`tarfile` + `ar` 格式），不依赖 `dpkg-deb`。`DebBuilder.build_deb` 接受调用者指定的输出目录；`AppBuilder` 构建完成后发布到目标目录下的 `apps/<resource-id>/artifacts/`。目标目录由 `flange status` 查看，产物以 `apps/<resource-id>/manifest.json` 为准。

第一次开发 App 请从[入门教程](../../docs/first-steps.md)开始；本页解释底层打包职责，完整流程见 [App 架构](../../docs/app-architecture.md)。

## 关键设计要点

- **Pure Python ar 打包**：`_write_ar` 手写 `!<arch>\n` 格式，将 `debian-binary`、`control.tar.gz`、`data.tar.gz` 三个成员写入 `.deb`，无外部工具依赖
- **control 文件生成**：`generate_control` 从 `AppSpec` 读取 `Package`、`Version`、`Architecture`、`Depends` 等字段，调用 `_generate_control_text` 生成标准 control 文本
- **postinst/prerm 生成**：有 `service_name` 时注入服务安装与移除钩子；安装只在 `systemd.auto_start: true` 时注册开机启动，不立即启动服务。移除时在存在 systemd 的运行环境中执行 `stop` + `disable`；chroot 中跳过这两个操作。
- **架构映射**：`_map_arch` 将 config 中的 `arm64` 等 Linux arch 转换为 Debian 命名（aarch64 → arm64）
- **shell 安全检查**：`_validate_shell_safe` 对 package name / version 正则校验，防止路径注入
- **AppSpec 集成**：`DebBuilder.build_from_spec` 读取 `app.yaml` 解析出的 `AppSpec`，一步到位生成 `.deb`

## 关键代码位置

- [`builder/deb.py:DebBuilder`](../../builder/deb.py) — 底层打包、control 生成与安装钩子
- [`builder/app_build.py:AppBuilder`](../../builder/app_build.py) — 构建隔离、打包调用与产物发布
