---
title: 源码管理 SourceManager
type: subsystem
status: stable
sources:
  - builder/source.py
related:
  - "[[ComponentBuilder 基类]]"
  - "[[rootfs 构建器]]"
  - "[[external_apps 装载]]"
updated: 2026-05-06
---

## TL;DR

`SourceManager` 管理 git 仓库（kernel/U-Boot/recovery 等）、tarball 与第三方 deb 到 `.build/sources/`；支持 shallow clone、commit 锁定、SHA 比对触发增量更新；app / firmware / deb 各走独立 `ensure_*` 方法。

## 关键设计要点

- **URL → 本地路径映射**：`ensure(component, config)` 从 config 读 `source.url` / `source.branch`，落到 `.build/sources/<component>/`
- **Shallow clone**：`_clone` 默认 `--depth 1`；config 指定 `commit` / `tag` 时追加 `--no-single-branch` 后 `_fetch_checkout` 精确切到该 ref
- **Ref 优先级**：`commit > tag > branch`；`tag` 用于不可变标签，避免 tag/branch 同名歧义
- **增量更新**：`_ensure_repo` 取当前 HEAD 与期望 ref 比对，不同才 `_fetch_reset_branch` / `_fetch_checkout`
- **Submodule**：`_update_submodules` 执行 `git submodule update --init --recursive`
- **Tarball**：`ensure_rootfs_tarball` 下载 ubuntu-base tar.gz + SHA256 校验
- **External app**：`ensure_app` 支持 git repo / 本地路径两种来源
- **External firmware**：`ensure_extra_firmware` 多源类型——`repo` clone 外部 git 仓库到 `extra-firmware/<name>/`；`kernel`/`bootloader`/`oot:<name>` 复用同 build 已 ensure 的源（不重复 clone），调用方通过 `component_sources` 注入对应路径
- **OOT 模块独立源**：`ensure_oot_source` clone 独立 git 仓库到 `oot-modules/<name>/` 作为 OOT 模块编译输入（路径语义与 `extra_firmware` 拷贝目标分离，避免 .o/.ko 残留污染固件部署）
- **External deb**：`ensure_extra_deb` wget 直下第三方 deb 到 `extra-debs/<name>/`，强制 sha256 校验；原子下载（`.download` 后缀 → 校验 → rename），失败清理 partial

## 关键代码位置

- [`builder/source.py:SourceManager`](../../builder/source.py) — 主类，L9
- [`builder/source.py:SourceManager.ensure`](../../builder/source.py) — 组件 git 源，L24
- [`builder/source.py:SourceManager.ensure_extra_firmware`](../../builder/source.py) — 外部 firmware repo
- [`builder/source.py:SourceManager.ensure_oot_source`](../../builder/source.py) — OOT 模块独立源
- [`builder/source.py:SourceManager.ensure_extra_deb`](../../builder/source.py) — 第三方 deb 直下，L103
- [`builder/source.py:SourceManager.ensure_rootfs_tarball`](../../builder/source.py) — tarball 下载
- [`builder/source.py:SourceManager.ensure_app`](../../builder/source.py) — app 源码
