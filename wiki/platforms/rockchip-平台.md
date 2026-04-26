---
title: rockchip 平台
type: platform
status: stable
sources:
  - builder/platforms/rockchip/__init__.py
  - builder/platforms/rockchip/kernel.py
  - builder/platforms/rockchip/bootloader.py
  - builder/platforms/rockchip/rootfs.py
  - builder/platforms/rockchip/boot.py
  - builder/platforms/rockchip/recovery.py
  - builder/platforms/rockchip/image.py
  - components/platform/rockchip/config.py
  - components/platform/rockchip/rk3566/config.py
  - ProjectSpec.md#164-三层继承
related:
  - "[[radxa-zero3w]]"
  - "[[tspi-rk3566]]"
  - "[[neons-core3566-nanob]]"
  - "[[orangepi-cm4]]"
  - "[[kernel 构建器]]"
  - "[[bootloader 构建器]]"
  - "[[USB 线刷协议]]"
  - "[[FlashStrategy 抽象]]"
updated: 2026-04-26
---

## TL;DR

Rockchip 系列平台；当前已落地 SoC 为 RK3566，覆盖 4 块板子。flange 的首选打样平台，构建流程与刷写工具均已验证。

## 关键设计要点

**策略类布局（`builder/platforms/rockchip/`）**

6 个策略文件 + 工厂入口：`kernel.py`、`bootloader.py`、`rootfs.py`、`boot.py`、`recovery.py`、`image.py`，由 `__init__.py:create_builder()` 按组件名分发。`ARTIFACT_NAMES` 表定义 collect key → 产物文件名映射（如 `("bootloader","idbloader") → "idbloader.img"`）。

**平台数据（`components/platform/rockchip/`）**

- `config.py`：第一层（platform 层），声明 `vendor`、`flash_tool: "upgrade_tool"`、arch、rkbin 仓库、packages 基线
- `rk3566/config.py`：第二层（SoC 层），声明 rkbin ini 前缀、U-Boot defconfig、kernel 仓库/分支/dts_dir、分区表
- 第三层（board 层）：位于 `components/board/<board>/config.py`，三层经 `deep_merge()` 合并

**刷写工具：`upgrade_tool`**

支持四种模式：DB（Download Boot）、WL（Write Loader）、RD（Read/Write 分区）、LD（设备轮询检测）。宿主机直接调用，不进 Docker。

**patches**

`components/platform/rockchip/patches/` 下有 `bootloader/`、`kernel/` 两类补丁目录；board 层也可有同名补丁目录，构建器依次应用。

## 易踩坑

- rkbin 的 `RKTRUST.ini` 区分 BL31/BL32；RK3566 使用 `RK3568TRUST.ini`（ini_prefix 与 trust_ini_prefix 不同，见 `rk3566/config.py`）
- DTB target 使用子目录相对路径（`rockchip/<dts>.dtb`），非内核完整路径，详见 [[kernel 构建器]]
