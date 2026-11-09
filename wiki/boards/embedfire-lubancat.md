---
title: embedfire-lubancat
type: board
status: wip
sources:
  - components/config/embedfire-lubancat.libsonnet
  - components/board/embedfire-lubancat-3/config.jsonnet
  - components/board/embedfire-lubancat-3-v2/config.jsonnet
  - components/board/embedfire-lubancat-5/config.jsonnet
  - components/board/embedfire-lubancat-5-v2/config.jsonnet
  - components/platform/rockchip/config.jsonnet
  - components/platform/rockchip/rk3576/config.jsonnet
  - components/platform/rockchip/rk3588/config.jsonnet
related:
  - "[[rockchip 平台]]"
  - "[[armsom-cm5-io]]"
  - "[[radxa-rock5b]]"
updated: 2026-10-21
---

> 阅读前提：先完成[初学指南](../../docs/first-steps.md)的环境准备，运行
> `flange target list embedfire-lubancat-3`（或另外三块）确认当前目标，再按野火官方硬件说明匹配介质、接口与下载模式。
> 本页是配置摘要；尚无实板验收记录。
> [返回板卡索引](index.md) · [构建与刷写流程](../workflows/lunch-build-flash-流程.md)

## TL;DR

野火（EmbedFire）鲁班猫系列，4 个 board 对应 2 款板 × 2 个硬件版本：

| board | SoC | 设备树 | v2 硬件差异 |
| --- | --- | --- | --- |
| `embedfire-lubancat-3` | RK3576 | `rk3576-lubancat-3` | — |
| `embedfire-lubancat-3-v2` | RK3576 | `rk3576-lubancat-3-v2` | RTC（BM8563，走 hym8563 驱动）由 i2c2 移到 i2c3 |
| `embedfire-lubancat-5` | RK3588 | `rk3588-lubancat-5` | — |
| `embedfire-lubancat-5-v2` | RK3588 | `rk3588-lubancat-5-v2` | DSI 背光 PWM 脚、fusb302 中断脚、PCIe2x1l0 使能脚调整 |

板卡硬件版本以丝印为准；v1/v2 设备树不互换。

## 关键设计要点

- **设备树放在 flange-kernel 树内**：dts 和它引用的全部 dtsi（csi / cam / dsi / dp / hdmi / hdmirx）同步自野火官方
  `LubanCat/kernel` 的 `lbc-develop-6.1` 分支，提交在 `flange-build/kernel` 的 `linux-6.1-stan-rkr5.1`（`d2eccb6c9eff`），
  并替换了此前随 neons kernel 带入、没有参与编译的旧版本；Makefile 登记了上表 4 个 dtb。
  `rk3588-lubancat-5.dts` 引用的 `dt-bindings/phy/jlsemi-dt-phy.h` 一并带入。flange 侧没有板级 kernel patch。
- **公共配置集中在一个文件**：`config/embedfire-lubancat.libsonnet` 的 `board(name, soc, dtb)` 生成完整板级配置，
  4 个 `config.jsonnet` 各只有一行调用。products = `default` / `desktop`，variants = `debug` / `release`；
  带 `rockchip-multimedia` 包，开发期设 `root_password: '1234'`。
- **其余全部沿用 SoC 层**：内核源 = 平台层 `rockchip-kernel`，GPU 走 RK3576 panfrost / RK3588 panthor，
  u-boot 用 generic `rk3576_defconfig` / `rk3588_defconfig`（Generic Distro Boot + extlinux），
  console 是 RK3576 `ttyS0` / RK3588 `ttyS2`（1500000），分区是 rockchip 公共 eMMC 布局（idbloader/uboot/boot/recovery/rootfs）。
- **无线不在首版范围**：两块板都没有板载 WiFi/BT 模组（无线靠 M.2 / PCIe 扩展），所以不带 OOT 驱动和 firmware。

## 易踩坑

- 板载 SPI NOR（`sfc1`）如果残留旧引导，BootROM 会优先从 SPI 启动，eMMC 上的 flange 引导就不会生效；这种情况要先擦掉 SPI。
- 野火 dts 里 MIPI 屏、摄像头、HDMI-RX 等 `#include` 都是注释状态。要启用的话，改 flange-kernel 中对应 dts 的 include，
  或者另写板级 dtso overlay。

## 验收状态

- 配置：4 个 board 共 16 个 target 通过 `tests/config` 全量校验。
- 设备树：4 个 dtb 在 flange-kernel 中编译通过，无警告。
- 内核（2026-10-21，flange-kernel `d2eccb6c9eff`）：`embedfire-lubancat-3-default-release`、`embedfire-lubancat-5-default-release` 的 `flange build kernel` 均成功（各约 5 分半），产出 `Image`、对应 dtb 与模块。
- 实板（刷写、启动、外设）：**未验收**。
