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
  - components/platform/rockchip/rk3588/config.py
  - components/platform/rockchip/rk3588s/config.py
  - ProjectSpec.md#164-三层继承
related:
  - "[[radxa-zero3w]]"
  - "[[tspi-rk3566]]"
  - "[[neons-core3566-nanob]]"
  - "[[orangepi-cm4]]"
  - "[[radxa-rock5b]]"
  - "[[kernel 构建器]]"
  - "[[bootloader 构建器]]"
  - "[[USB 线刷协议]]"
  - "[[FlashStrategy 抽象]]"
updated: 2026-05-06
---

## TL;DR

Rockchip 系列平台；当前已落地 SoC：RK3566（4×A55，4 块板）+ RK3588（4×A76+4×A55，1 块板 ROCK 5B），共 5 块板。flange 的首选打样平台，构建流程与刷写工具均已验证。

## 关键设计要点

**策略类布局（`builder/platforms/rockchip/`）**

6 个策略文件 + 工厂入口：`kernel.py`、`bootloader.py`、`rootfs.py`、`boot.py`、`recovery.py`、`image.py`，由 `__init__.py:create_builder()` 按组件名分发。`ARTIFACT_NAMES` 表定义 collect key → 产物文件名映射（如 `("bootloader","idbloader") → "idbloader.img"`）。

**平台数据（`components/platform/rockchip/`）**

- `config.py`：第一层（platform 层），声明 `vendor`、`flash_tool: "upgrade_tool"`、arch、rkbin 仓库、packages 基线
- `rk3566/config.py` / `rk3588/config.py` / `rk3588s/config.py`：第二层（SoC 层），声明 rkbin ini 前缀、U-Boot defconfig、kernel 仓库/分支/defconfig list、分区表
- 第三层（board 层）：位于 `components/board/<board>/config.py`，三层经 `deep_merge()` 合并

**SoC 分支差异**

- RK3566 系列：`linux-6.1-stan-rkr4.1-buildroot`（GPU 走 BSP mali_kbase）
- RK3588/RK3588S：`linux-6.1-stan-rkr5.1`，dts 已切到 mainline panthor (`arm,mali-valhall-csf`)；SoC 配置通过 `rk3588_panthor.config` fragment 关 mali_kbase 启 `CONFIG_DRM_PANTHOR=m`，固件 blob `mali_csffw.bin` 走 `extra_firmware source: kernel` 从 BSP 内 vendor 子目录拷贝。**不能用 rkr4.1**——其 mali_kbase fork 不识别 RK3588 r0p0 status 5 silicon，会在 `kbase_hwaccess_pm_powerup` mutex 死锁

**刷写工具：`upgrade_tool`**

支持四种模式：DB（Download Boot）、WL（Write Loader）、RD（Read/Write 分区）、LD（设备轮询检测）。宿主机直接调用，不进 Docker。

**patches**

`components/platform/rockchip/patches/` 下有 `bootloader/`、`kernel/` 两类补丁目录；board 层也可有同名补丁目录，构建器依次应用。

## 易踩坑

- rkbin 的 `RKTRUST.ini` 区分 BL31/BL32；RK3566 使用 `RK3568TRUST.ini`（ini_prefix 与 trust_ini_prefix 不同，见 `rk3566/config.py`）
- DTB target 使用子目录相对路径（`rockchip/<dts>.dtb`），非内核完整路径，详见 [[kernel 构建器]]
- RK3588 板不要用 vendor `<board>-rk3588_defconfig`（含 androidboot 风格固定 bootargs，绕过 extlinux），统一用 generic `rk3588_defconfig`
