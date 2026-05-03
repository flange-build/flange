---
title: 源码管理 SourceManager
type: subsystem
status: stable
sources:
  - builder/source.py
related:
  - "[[ComponentBuilder 基类]]"
  - "[[external_apps 装载]]"
updated: 2026-05-03
---

## TL;DR

`SourceManager` 管理 git 仓库（kernel/U-Boot/recovery 等）和 tarball 到 `.build/sources/`；支持 shallow clone 与 commit 锁定；SHA 比对触发增量更新；app 源码通过独立方法 `ensure_app` 处理。

## 关键设计要点

- **URL → 本地路径映射**：`ensure(component, config)` 从 config 中读 `source.url` 与 `source.branch`，以组件名为子目录落在 `.build/sources/<component>/`
- **Shallow clone**：`_clone` 默认 `--depth 1` 减小克隆体积；若 config 指定 `commit` 或 `tag` 则追加 `--no-single-branch` 后 `_fetch_checkout` 精确切到该 ref
- **Ref 优先级**：`commit > tag > branch`。`tag` 字段用于固定不可变标签（如 `0.2.21`），避免 `branch` 路径对 tag/branch 同名时的歧义错误
- **增量更新**：`_ensure_repo` 调用 `_rev_parse_ref` 取当前 HEAD；与 config 中期望 ref 比对，不同才 `_fetch_reset_branch` 或 `_fetch_checkout`
- **Submodule 支持**：`_update_submodules` 在 clone/update 后执行 `git submodule update --init --recursive`
- **Tarball 支持**：`ensure_rootfs_tarball` 下载 ubuntu-base tar.gz 并验证 SHA256，存入 `.build/sources/rootfs-base/`
- **External app 源码**：`ensure_app` 接受 app 配置中的 `source` 块，支持 git repo 和本地路径两种来源

## 关键代码位置

- [`builder/source.py:SourceManager`](../../builder/source.py) — 主类，L8
- [`builder/source.py:SourceManager.ensure`](../../builder/source.py) — 组件 git 源，L23
- [`builder/source.py:SourceManager._clone`](../../builder/source.py) — shallow clone，L268
- [`builder/source.py:SourceManager.ensure_rootfs_tarball`](../../builder/source.py) — tarball 下载，L102
- [`builder/source.py:SourceManager.ensure_app`](../../builder/source.py) — app 源码，L114
