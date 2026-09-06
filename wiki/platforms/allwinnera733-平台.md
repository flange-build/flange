---
title: allwinnera733 平台
type: platform
status: wip
sources:
  - builder/platforms/allwinnera733/__init__.py
  - builder/platforms/allwinnera733/kernel.py
  - builder/platforms/allwinnera733/bootloader.py
  - builder/platforms/allwinnera733/rootfs.py
  - builder/platforms/allwinnera733/boot.py
  - builder/platforms/allwinnera733/recovery.py
  - builder/platforms/allwinnera733/image.py
  - components/platform/allwinnera733/config.jsonnet
  - components/platform/allwinnera733/a733/config.jsonnet
  - openspec/specs/allwinnera733-platform/spec.md
  - openspec/specs/allwinnera733-flash/spec.md
  - docs/development-guide.md
  - docs/extension-guide.md
related:
  - "[[radxa-cubie-a7z]]"
  - "[[bootloader 构建器]]"
  - "[[USB 线刷协议]]"
  - "[[FlashStrategy 抽象]]"
updated: 2026-09-05
---

> 阅读前提：先读[架构总览](../concepts/架构总览.md)，并从[板卡索引](../boards/index.md)确认型号。
> 本页保留平台机制与历史适配记录；芯片支持、产物可构建和实机验收是不同边界。
> 当前操作见[开发指南](../../docs/development-guide.md)，扩展步骤见[扩展指南](../../docs/extension-guide.md)。

## TL;DR

Allwinner A733（sun60iw2p1）平台；status: wip，进行中。首板为 Radxa Cubie A7Z。与 Rockchip 最大差异在 bootloader 流程（sunxi 体系）与刷写工具（SD 卡 dd，FEL 待实现）。

## 关键设计要点

**策略类布局（`builder/platforms/allwinnera733/`）**

结构与 Rockchip 镜像：同样 6 个策略文件，`__init__.py:create_builder()` 分发。已在代码中注册：`kernel`、`bootloader`、`rootfs`、`boot`、`recovery`、`image` 全部组件。

**与 Rockchip 的主要差异**

| 维度 | Rockchip | allwinnera733 |
|------|----------|---------------|
| bootloader | U-Boot + rkbin（BL31/BL32）| sunxi U-Boot（u-boot-aw2501） |
| bootloader 产物 | idbloader.img / u-boot.itb | boot0_sdcard.bin / boot_package.fex |
| boot 配置 | extlinux / overlays | extlinux + sunxi DTB（sunxi.dtb） |
| 刷写工具 | upgrade_tool | 当前 dd（SD 卡）；FEL / PhoenixSuit 待实现 |
| flash_tool 字段 | `"upgrade_tool"` | `"dd"` |

**当前实现状态**

已落地：kernel（BSP 聚合仓库）、bootloader（sunxi 源码构建）、boot（extlinux + recovery.conf）、rootfs、recovery、image（raw.img dd）。刷写仅 SD 卡 dd；FEL / PhoenixSuit 待实现（见 `allwinnera733-flash/spec.md`）。

**Recovery Boot 选择**

A733 经 Allwinner RTC reboot flag 区分普通启动 vs recovery；`recoveryctl loader` 传 `bootloader` reason 进 fastboot（区别于 Rockchip misc 分区）。

**patches**

`components/platform/allwinnera733/patches/bootloader/` 已存在；kernel 补丁目录同结构预留。

**SoC 层默认 deb（`+extra_debs`）**

a733 SoC 层声明 `+extra_debs` 给所有 a733 板默认安装：
- `xserver-xorg-img-bxm`：PowerVR BXM userspace driver（X 服务器 DDX）
- `libcedarc-dev v2.0`：Allwinner CedarC VE 硬件解码用户态库（OMX 组件、VDecoder/VEncoder API、H.264/H.265/VP9/VP8/MPEG2/MPEG4/MJPEG/AVS/AVS2 解码插件）。VE 内核模块 `sunxi-ve` 通过 DT compatible 自动 probe 加载，无需 modules-load 条目

均来自 `radxa-pkg/allwinner-prebuilt-extra` GitHub release，sha256 锁定。

## 易踩坑

- kernel 源码为聚合仓库 `linux-a733`（含 bsp/ 与 device-a733/ 子路径），编译前需 `_integrate_bsp` 建 symlink；详见 [[kernel 构建器]]
- BSP GPU 驱动（`bsp/modules/gpu/`）使用独立构建系统，不兼容内核 kbuild（kbuild 会静默跳过），需通过 [[out-of-tree 模块]] 机制编译
- 刷写当前走 dd 整盘，不支持分区级更新；FEL 模式上线前现场维护依赖 SD 卡重刷
