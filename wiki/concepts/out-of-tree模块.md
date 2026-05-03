---
title: out-of-tree 模块
type: concept
status: stable
sources:
  - builder/platforms/allwinnera733/kernel.py
  - components/platform/allwinnera733/a733/config.py
  - builder/config/merge.py
related:
  - "[[三层继承]]"
  - "[[allwinnera733 平台]]"
  - "[[FINAL_CONFIG]]"
updated: 2026-05-03
---

## TL;DR

out-of-tree（OOT）内核模块指源码在内核树外、使用独立构建系统编译的内核模块。flange 通过 `kernel.oot_modules` 配置声明，在 `make modules` 后逐个编译并统一安装到 rootfs。

## 关键设计要点

- **配置声明**：在 SoC 或 board 的 `config.py` 中，`kernel.oot_modules` 列表声明每个 OOT 模块：
  - `dir`：构建入口目录（相对内核源码树）
  - `label`：显示名
  - `make_args`：传给 make 的参数，支持 `{kernel_src}` 模板变量
  - `ko_pattern`：glob 模式匹配编译产物 .ko
  - `pre_build` / `post_build`：编译前后 shell 钩子（如临时补丁）
- **编译流程**：`kernel.py` 的 `compile()` 在 `make modules` 完成后调用 `_compile_oot_modules()`，遍历声明列表逐个编译
- **安装流程**：`_install_oot_modules()` 扫描 `ko_pattern` 产物，strip 后安装到 `_modules_staging/lib/modules/<version>/updates/`，并更新 `modules.dep`
- **三层继承**：SoC 层声明的 `oot_modules` 自动被 board 继承；board 追加额外模块需用 `+oot_modules`（`deep_merge` 的 list 追加语义）

## 实例

Allwinner A733 的 PowerVR BXM GPU 驱动（img-bxm / Rogue DDK）：

- `bsp/modules/gpu/` 的 Makefile 使用 LICHEE_* 变量，kbuild 会静默跳过
- DDK kbuild.mk 未传 `ARCH=arm64`，需 `pre_build` 临时注入 sed 补丁
- 编译产物 `pvrsrvkm.ko` 通过 `ko_pattern` 匹配并安装

## 关键代码位置

- [`builder/platforms/allwinnera733/kernel.py:_compile_oot_modules`](../../builder/platforms/allwinnera733/kernel.py) — OOT 编译流程
- [`builder/config/merge.py:deep_merge`](../../builder/config/merge.py) — `+key` 追加语义
