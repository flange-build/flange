---
title: kernel 构建器
type: component
status: stable
sources:
  - builder/platforms/rockchip/kernel.py
  - builder/platforms/allwinnera733/kernel.py
  - builder/base.py
  - ProjectSpec.md#63-框架与策略分离
related:
  - "[[ComponentBuilder 基类]]"
  - "[[rockchip 平台]]"
  - "[[allwinnera733 平台]]"
  - "[[Docker 执行封装]]"
  - "[[内容哈希与增量构建]]"
updated: 2026-04-26
---

## TL;DR

跨平台内核构建：获取源码 → 应用补丁 → defconfig + make → 收集 Image/DTB/modules。平台子类实现策略；`ComponentBuilder.build`（L29）编排生命周期。

## 关键设计要点

- **configure**：`make <defconfig>`；defconfig 来自 `config["kernel"]["defconfig"]`
- **compile**：目标为 `Image`、`<dts_dir>/<dts>.dtb`、`modules`；`KCFLAGS=-Wno-error`；`modules_install` 加 `INSTALL_MOD_STRIP=1`
- **symlink 清理**：`modules_install` 产出的 `source/build` 链接指向容器绝对路径，deploy 会报错；编译后遍历删除
- **collect 产物**：`image`、`dtb`、`modules`（_modules_staging）、`dtbos`
- **Allwinner A733**：linux-a733 聚合仓库（kernel + bsp + device）；`_integrate_bsp` symlink bsp/；所有 make 加 `BSP_TOP=bsp/`（`AllwinnerA733KernelBuilder`，L14）

## 关键代码位置

- [`builder/platforms/rockchip/kernel.py:RockchipKernelBuilder`](../../builder/platforms/rockchip/kernel.py) — Rockchip 策略，L7
- [`builder/platforms/rockchip/kernel.py:compile`](../../builder/platforms/rockchip/kernel.py) — 三目标编译，L16
- [`builder/platforms/allwinnera733/kernel.py:AllwinnerA733KernelBuilder`](../../builder/platforms/allwinnera733/kernel.py) — A733 聚合仓库，L14
- [`builder/base.py:ComponentBuilder.build`](../../builder/base.py) — 生命周期入口，L29

## 易踩坑

- DTB 目标用 `<dts_dir>/<dts>.dtb` 子目录相对路径（非 arch/.../dts/ 完整路径）；kbuild 按此展开（注释于 `rockchip/kernel.py:19`）
- macOS 大小写不敏感 FS：`git checkout -f` 对大小写冲突文件非零退出但已完成；基类 `check=False` 忽略
