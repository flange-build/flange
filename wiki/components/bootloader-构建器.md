---
title: bootloader 构建器
type: component
status: stable
sources:
  - builder/platforms/rockchip/bootloader.py
  - builder/platforms/allwinnera733/bootloader.py
  - builder/base.py
related:
  - "[[ComponentBuilder 基类]]"
  - "[[rockchip 平台]]"
  - "[[allwinnera733 平台]]"
  - "[[U-Boot 启动链]]"
updated: 2026-04-26
---

## TL;DR

U-Boot + SPL 编译及固件打包。Rockchip 解析 RKTRUST/RKBOOT INI → `idbloader.img` + `u-boot.itb`；Allwinner 从 u-boot-aw2501（7 子模块）→ `boot0_sdcard.bin` + `boot_package.fex`。

## 关键设计要点

**Rockchip**（`RockchipBootloaderBuilder`，L8）：
- configure：`make <defconfig>`（ARCH=arm）；compile：默认 target → `u-boot.itb`
- `_parse_trust_ini`（L64）取 BL31/BL32；`_parse_loader_ini`（L75）取 DDR/SPL → `idbloader.img`；miniloader 名从 `[OUTPUT]` 读；collect：`bootloader`、`idbloader`、`miniloader`

**Allwinner A733**（`AllwinnerA733BootloaderBuilder`，L19）：
- 重写 `build()`，`make -j1`（串行，`sys_config.bin` 并发有 race）；工具链：Linaro ARM + RISC-V（`_ensure_toolchain`，L79）
- collect：`boot0_sdcard`、`boot0_ufs`、`boot_package`（实际存在子集）

## 关键代码位置

- [`builder/platforms/rockchip/bootloader.py:compile`](../../builder/platforms/rockchip/bootloader.py) — 两步打包，L17
- [`builder/platforms/rockchip/bootloader.py:_parse_trust_ini`](../../builder/platforms/rockchip/bootloader.py) — BL31/BL32，L64
- [`builder/platforms/allwinnera733/bootloader.py:build`](../../builder/platforms/allwinnera733/bootloader.py) — A733 构建，L22

## 易踩坑

- Allwinner 必须 `-j1`：`sys_config.bin` 多 target 共享，并行互相覆盖
- Rockchip miniloader 名称从 `[OUTPUT].PATH` 动态读，勿硬编码
