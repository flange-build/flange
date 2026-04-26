---
title: deb 打包引擎
type: subsystem
status: stable
sources:
  - builder/deb.py
related:
  - "[[app 打包系统]]"
  - "[[scaffold 生成器]]"
updated: 2026-04-26
---

## TL;DR

`builder/deb.py` 提供纯 Python `.deb` 构建能力（`tarfile` + `ar` 格式），不依赖 `dpkg-deb`；`DebBuilder.build_deb` 生成符合 Debian 规范的二进制包，由 `AppBuilder` 调用后输出到 `.build/deb/`。

## 关键设计要点

- **Pure Python ar 打包**：`_write_ar` 手写 `!<arch>\n` 格式，将 `debian-binary`、`control.tar.gz`、`data.tar.gz` 三个成员写入 `.deb`，无外部工具依赖
- **control 文件生成**：`generate_control` 从 `AppSpec` 读取 `Package`、`Version`、`Architecture`、`Depends` 等字段，调用 `_generate_control_text` 生成标准 control 文本
- **postinst/prerm 生成**：`_generate_postinst` 生成 systemd `enable` + `start` 钩子；`_generate_prerm` 生成 `stop` + `disable`；有 `service_name` 时自动注入
- **架构映射**：`_map_arch` 将 config 中的 `arm64` 等 Linux arch 转换为 Debian 命名（aarch64 → arm64）
- **shell 安全检查**：`_validate_shell_safe` 对 package name / version 正则校验，防止路径注入
- **AppSpec 集成**：`DebBuilder.build_from_spec` 读取 `app.yaml` 解析出的 `AppSpec`，一步到位生成 `.deb`

## 关键代码位置

- [`builder/deb.py:DebBuilder`](../../builder/deb.py) — 主类，L420
- [`builder/deb.py:DebBuilder.build_deb`](../../builder/deb.py) — 构建入口，L439
- [`builder/deb.py:generate_control`](../../builder/deb.py) — control 生成，L213
- [`builder/deb.py:_write_ar`](../../builder/deb.py) — ar 格式写入，L373
- [`builder/deb.py:_generate_postinst`](../../builder/deb.py) — systemd 钩子，L142
