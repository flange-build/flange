## Context

rk3506b（ATK-DLRK3506B）已打通 Rockchip ARM32 + SPI NAND + vendor FIT + UBI 路由
（spec `rockchip-arm32-spinand-ubi`）。RV1106 与之同属单核/多核 Cortex-A7、SPI NAND 启动，
差异集中在 DDR 初始化 blob、U-Boot defconfig、内核 DTS 与 TOS/OP-TEE 组合。

## Goals / Non-Goals

目标：Luckfox Pico Max 从 SPI NAND 启动到 rootfs，串口 `ttyFIQ0` 登录、以太网可用、USB OTG
可作 gadget；Pro 共用配置。非目标见 proposal。

## Decisions

1. **SoC 层照 rk3506b 结构建立，不新增 builder 代码**。先以 `RV1106MINIALL.ini` 生成 idblock，
   U-Boot 用 `rv1106_defconfig`（如需 SPI NAND/SFC 片段，参考官方 `rk-sfc.config`）。
   RV1106 无 BL31；`trust_mode` 按 rkbin INI 实际内容确定（tos 或无 trust），在任务 1.1 中核实。
2. **DTS 走板级内核补丁新增文件**，include 6.1 树内 `rv1106.dtsi`/`rv1106g3.dtsi` 等，
   不 include 官方 `rv1106-luckfox-pico-pro-max-ipc.dtsi`（依赖 5.10 树的摄像头驱动）。
   CMA 按官方 66M 起步，Pro（128MB）若内存紧张再按 product 调整。
3. **分区合并 oem/userdata 到 rootfs**：flange 不使用官方应用分区，rootfs 取剩余空间约 250M，
   UBI 几何按实际 SPI NAND（2 KiB page / 128 KiB PEB 典型值）声明，任务中以芯片手册或
   U-Boot `mtd info` 核实，禁止猜测。
4. **默认 product 用最小 Ubuntu**：BSP 必须能在没有 Alpine 层的仓库中独立构建与验证；
   包集合裁剪为 base 中必要项，保证 UBI 容量充足。

## Risks / Trade-offs

- 6.1 树 RV1106 驱动成熟度低于 5.10 SDK → 首版只启用基础外设，以太网/USB 不通时回退评估 DTS。
- 同一 rkbin 分支 DDR blob 与官方 SDK 版本不同 → 实机不启动时比对官方 `rv1106_ddr_924MHz_*.bin`。
- 128 MB 的 Pro 运行 Ubuntu 较紧张 → Ubuntu product 仅作 BSP 验证，产品化走 Alpine。

## Migration Plan

纯新增；现有板卡 golden 与回归必须零 diff。
