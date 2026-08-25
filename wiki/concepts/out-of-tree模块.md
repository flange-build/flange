---
title: out-of-tree 模块
type: concept
status: stable
sources:
  - builder/kernel_base.py
  - builder/source.py
  - builder/cache.py
  - components/platform/allwinnera733/a733/config.jsonnet
  - components/board/radxa-rock5b/config.jsonnet
related:
  - "[[三层继承]]"
  - "[[源码管理 SourceManager]]"
  - "[[allwinnera733 平台]]"
  - "[[FINAL_CONFIG]]"
updated: 2026-08-26
---

## TL;DR

out-of-tree（OOT，树外）内核模块由 `kernel.oot_modules` 声明；独立仓库统一放入顶层 `sources`，再由 `kernel.oot_sources.<name>.source` 引用。

## 关键设计要点

- `kernel.oot_modules` 声明 `dir`、`label`、`make_args`、`ko_pattern` 以及可选构建钩子。
- `sources.<name>` 唯一描述 remote `{url,branch|commit,...}` 或 local `{local_path}` source。
- `kernel.oot_sources.<name>: {source: {name, subpath?}}` 复用共享 checkout。
- `SourceManager.ensure_oot_source()` 注入 `{<name>_src}` 模板变量；`{kernel_src}` 始终可用。
- `_install_oot_modules()` 将模块装入 staging，最后运行 depmod 重建索引。
- Jsonnet 各层用 `oot_modules+: [...]` 追加模块，无 Python merge alias。

## 实例

- A733 / img-bxm：源码位于 kernel tree，只使用 `{kernel_src}`。
- ROCK 5B / rkwifibt：`sources.rkwifibt` 固定仓库 revision，`kernel.oot_sources.rkwifibt.source` 引用它；额外 firmware 复用同一 source 与 subpath。

## 关键代码位置

- [`builder/kernel_base.py:KernelBuilder`](../../builder/kernel_base.py) — OOT 编译与安装
- [`builder/source.py:SourceManager.ensure_oot_source`](../../builder/source.py) — canonical source 解析
- [`builder/cache.py`](../../builder/cache.py) — source 内容与 revision 哈希
