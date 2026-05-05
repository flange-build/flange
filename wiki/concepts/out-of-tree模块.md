---
title: out-of-tree 模块
type: concept
status: stable
sources:
  - builder/kernel_base.py
  - builder/source.py
  - builder/cache.py
  - components/platform/allwinnera733/a733/config.py
  - components/board/radxa-rock5b/config.py
  - builder/config/merge.py
related:
  - "[[三层继承]]"
  - "[[源码管理 SourceManager]]"
  - "[[allwinnera733 平台]]"
  - "[[FINAL_CONFIG]]"
updated: 2026-05-06
---

## TL;DR

out-of-tree（OOT）内核模块指源码在内核树外、使用独立构建系统编译的内核模块。flange 通过 `kernel.oot_modules` 配置声明，在 `make modules` 后逐个编译并统一安装到 rootfs；编译入口若是独立 git 仓库则通过 `kernel.oot_sources` 声明，按 `{<name>_src}` 模板变量注入。

## 关键设计要点

- **配置声明**：`kernel.oot_modules` 列表声明每个 OOT 模块：
  - `dir`：构建入口目录，支持 `{kernel_src}` / `{<oot_source_name>_src}` 模板变量
  - `label`：显示名
  - `make_args`：传给 make 的参数，同样支持模板变量
  - `ko_pattern`：glob 模式匹配编译产物 .ko
  - `pre_build` / `post_build`：编译前后 shell 钩子（如临时补丁）
- **独立源声明**：`kernel.oot_sources: {<name>: {repo, branch/commit/tag, ...}}`。每个源由 `SourceManager.ensure_oot_source` clone 到 `.build/sources/oot-modules/<name>/`，路径作为 `{<name>_src}` 注入模板（`-` 替换为 `_`）。仓库 git HEAD 通过 `cache._mix_kernel_oot_sources` 入 kernel hash —— branch 跟踪场景（如 `branch: develop`）远端推进会自动级联重 build
- **编译流程**：`_compile_oot_modules()` 先 ensure 所有 oot_sources 构造模板字典，再遍历 oot_modules 逐个 make
- **安装流程**：`_install_oot_modules()` strip 后装到 `_modules_staging/lib/modules/<version>/updates/`，**末尾跑 `depmod -b <staging> <release>` 重建 modules.{dep,alias,symbols} 与 `.bin` 索引** —— 不刷 alias，PCI/USB hotplug 拿到 MODALIAS 查不到 module，开机不自动 load
- **三层继承**：SoC 层声明的 `oot_modules` 自动被 board 继承；board 追加用 `+oot_modules`（list 追加语义）

## 实例

- **A733 / img-bxm**（PowerVR BXM GPU）：内核源内嵌，仅引用 `{kernel_src}` 模板变量，不需要 `oot_sources`
- **ROCK 5B / rkwifibt**（RTL8852BE WiFi6+BT）：独立 git 仓库，`oot_sources.rkwifibt: {repo, branch: develop}` + `oot_modules` 引用 `{rkwifibt_src}/drivers/rtl8852be`；编出 `8852be.ko`。BT 部分 in-tree btusb，固件通过 `extra_firmware` `source: oot:rkwifibt` 复用同源拷文件

## 关键代码位置

- [`builder/kernel_base.py:KernelBuilder`](../../builder/kernel_base.py) — OOT 编译/安装、模板变量构造、depmod
- [`builder/source.py:ensure_oot_source`](../../builder/source.py) — 独立源 clone
- [`builder/cache.py:_mix_kernel_oot_sources`](../../builder/cache.py) — git HEAD 入 hash
- [`builder/config/merge.py:deep_merge`](../../builder/config/merge.py) — `+key` 追加语义
