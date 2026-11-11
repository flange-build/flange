# allwinnera733 平台

> 阅读前提：先读[架构总览](../build-system-design.md)，并从[板卡索引](../boards/README.md)确认型号。
> 本页说明平台机制与已确认的适配约束；芯片支持、产物可构建和实机验收是不同边界。
> 当前操作见[开发指南](../development-guide.md)，扩展步骤见[扩展指南](../extension-guide.md)。

## 概述

Allwinner A733（sun60iw2p1）平台，覆盖 Radxa Cubie A7A 与 A7Z。与 Rockchip 最大差异在 bootloader 流程（sunxi 体系）与刷写工具（SD 卡 dd，FEL 待实现）。

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

已落地：kernel（BSP 聚合仓库）、bootloader（sunxi 源码构建）、boot（extlinux + recovery.conf）、rootfs、recovery、image（raw.img dd）。刷写仅 SD 卡 dd；当前没有 FEL / PhoenixSuit 刷写实现。

**Recovery Boot 选择**

A733 经 Allwinner RTC reboot flag 区分普通启动 vs recovery；`recoveryctl loader` 传 `bootloader` reason 进 fastboot（区别于 Rockchip misc 分区）。

**patches**

`components/platform/allwinnera733/patches/bootloader/` 已存在；kernel 补丁目录同结构预留。

**平台层用户态驱动（`rootfs.extra_debs`）**

平台层为 A733 板声明以下预编译包：
- `xserver-xorg-img-bxm`：PowerVR BXM userspace driver（X 服务器 DDX）
- `libcedarc-dev v2.0`：Allwinner CedarC VE 硬件解码用户态库（OMX 组件、VDecoder/VEncoder API、H.264/H.265/VP9/VP8/MPEG2/MPEG4/MJPEG/AVS/AVS2 解码插件）。VE 内核模块 `sunxi-ve` 通过 DT compatible 自动 probe 加载，无需 modules-load 条目

均来自 `radxa-pkg/allwinner-prebuilt-extra` GitHub release，sha256 锁定。

## 易踩坑

- kernel 源码为聚合仓库 `linux-a733`（含 bsp/ 与 device-a733/ 子路径），编译前需 `_integrate_bsp` 建 symlink；详见 [kernel 构建器](../components/kernel.md)
- BSP GPU 驱动（`bsp/modules/gpu/`）使用独立构建系统，不兼容内核 kbuild（kbuild 会静默跳过），需通过 [out-of-tree 模块](../hardware/kernel-modules.md) 机制编译
- 刷写当前走 dd 整盘，不支持分区级更新；FEL 模式上线前现场维护依赖 SD 卡重刷
