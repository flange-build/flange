---
title: armsom-cm5-io
type: board
status: wip
sources:
  - components/board/armsom-cm5-io/config.py
  - components/platform/rockchip/rk3576/config.py
related:
  - "[[rockchip 平台]]"
  - "[[radxa-rock5b]]"
updated: 2026-06-15
---

## TL;DR

ArmSoM CM5 IO，首颗 **RK3576**（4×A72+4×A53，Mali-G52）板。打通 RK3576 平台
构建链：可构建、可启动、GPU 走 **mainline panfrost** 开源驱动。实测启动成功、
panfrost 渲染（GLES 3.1）通过。

## 关键设计要点

- **SoC 层对齐 rk3588**：`rk3576/config.py` 复用同一 argon BSP
  `linux-6.1-stan-rkr5.1` + `rockchip_linux_defconfig`；差异仅 GPU fragment
  （`rk3576_panfrost.config` 替 `rk3588_panthor.config`）。`rkbin` ini_prefix /
  mkimage_chip 均 `rk3576`，bootloader 用 generic `rk3576_defconfig`。
- **GPU = panfrost（非 panthor）**：G52 是 Bifrost，开源驱动是 panfrost
  （panthor 只认 Valhall-CSF，带不动 G52）。dts gpu 节点 compatible 本就是
  `arm,mali-bifrost`、`status=okay`（在 `rk3576-armsom-cm5.dtsi`），与 panfrost
  of_match 天然对位，无需 CSF firmware。Vulkan(PanVK) 在 Bifrost v7 仅实验级。
- **dts 已在 BSP 树内**：`rk3576-armsom-cm5-io.dts` 及 dtsi 随 argon rkr5.1 自带，
  仅需补 kernel-rockchip `Makefile` 的 dtb 条目（commit 3d55028）。
- **OP-TEE**：随全平台 patch `0006` 打包进 u-boot.itb（详见 [[rockchip 平台]]
  OP-TEE 段）。console = `ttyS0,1500000`（UART0，rk3576 serial-id=0）。
- **WiFi/BT**（独立 change `add-armsom-cm5-io-wifi-bt`，进行中）：板载
  BW3752-50B1（≈AP6275S/BCM43752），WiFi SDIO 走 Rockchip OOT bcmdhd、BT
  UART4，board 层补三件套固件 + 两条 kernel patch。

## 易踩坑

- `CONFIG_SPL_OPTEE=y` 会拉 armv7 `spl_optee.S`，arm64 SPL 编不过——OP-TEE 打包
  靠 `0006` 取消注释 `gen_bl32_node`，不靠该符号。
