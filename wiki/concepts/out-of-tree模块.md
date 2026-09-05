---
title: out-of-tree 模块
type: concept
status: stable
sources:
  - builder/kernel_base.py
  - builder/source.py
  - builder/component_plan.py
  - components/platform/allwinnera733/a733/config.jsonnet
  - components/board/radxa-rock5b/config.jsonnet
  - docs/development-guide.md
  - docs/extension-guide.md
related:
  - "[[三层继承]]"
  - "[[源码管理 SourceManager]]"
  - "[[allwinnera733 平台]]"
  - "[[FINAL_CONFIG]]"
updated: 2026-09-05
---

> 阅读前提：先确认[板卡配置与硬件范围](../boards/index.md)，再阅读本专题。
> 下文接线、内核/固件行为和测试结果只覆盖注明的设备、版本与产品；历史排障记录不代表全部目标已验收。
> 当前构建入口见[开发指南](../../docs/development-guide.md)，新增驱动/配置见[扩展指南](../../docs/extension-guide.md)。

## TL;DR

out-of-tree（OOT，树外）内核模块由 `kernel.oot_modules` 声明；独立仓库统一放入顶层 `sources`，再由 `kernel.oot_sources.<name>.source` 引用。

## 关键设计要点

- `kernel.oot_modules` 声明 `dir`、`label`、`make_args`、`ko_pattern` 以及可选构建钩子。
- `sources.<name>` 唯一描述 remote `{url,branch|commit,...}` 或 local `{local_path}` source。
- `kernel.oot_sources.<name>: {source: {name, subpath?}}` 复用来源定义；实际编译使用当前目标隔离工作树，不写共享下载仓库。
- `SourceManager.ensure_oot_source()` 注入 `{<name>_src}` 模板变量；`{kernel_src}` 始终可用。
- `_install_oot_modules()` 将模块装入 staging，最后运行 depmod 重建索引。
- Jsonnet 各层用 `oot_modules+: [...]` 追加模块，无 Python merge alias。

## 实例

- A733 / img-bxm：源码位于 kernel tree，只使用 `{kernel_src}`。
- ROCK 5B / rkwifibt：`sources.rkwifibt` 固定仓库 revision，`kernel.oot_sources.rkwifibt.source` 引用它；额外 firmware 复用同一 source 与 subpath。

## 关键代码位置

- [`builder/kernel_base.py:KernelBuilder`](../../builder/kernel_base.py) — OOT 编译与安装
- [`builder/source.py:SourceManager.ensure_oot_source`](../../builder/source.py) — canonical source 解析
- [`builder/component_plan.py`](../../builder/component_plan.py) — source 内容与 revision 的具名输入
