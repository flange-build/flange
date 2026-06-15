---
title: armsom-cm5-io
type: board
status: wip
sources:
  - components/board/armsom-cm5-io/config.py
  - components/board/armsom-cm5-io/patches/kernel/0001-dts-armsom-cm5-wifi-chip-ap6275s.patch
  - components/board/armsom-cm5-io/overlay/etc/modprobe.d/bcmdhd.conf
  - components/platform/rockchip/rk3576/config.py
related:
  - "[[rockchip 平台]]"
  - "[[radxa-rock5b]]"
  - "[[orangepi-cm4]]"
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
- **WiFi/BT**（change `add-armsom-cm5-io-wifi-bt`）：板载 BW3752-50B1
  （BCM43752/≈AP6275S）。WiFi 走 **rkwifibt OOT bcmdhd**——`+defconfig` 关内建
  `CONFIG_BCMDHD`+`CONFIG_BRCMFMAC`、`+oot_modules` 编 OOT `bcmdhd.ko`（对齐
  rock5b 模式）；固件含关键 `clm_bcm43752a2_ag.blob` 从 rkwifibt 仓
  （`firmware/broadcom/AP6275S`）部署到 `/lib/firmware/brcm/`；overlay
  `modprobe.d/bcmdhd.conf` 用 `firmware_path` 覆盖 OOT 默认 Android 路径。实测
  country CN、扫到 2.4G+5G AP。BT(UART4) 固件就绪、不预装用户态栈。

## 易踩坑

- `CONFIG_SPL_OPTEE=y` 会拉 armv7 `spl_optee.S`，arm64 SPL 编不过——OP-TEE 打包
  靠 `0006` 取消注释 `gen_bl32_node`，不靠该符号。
- WiFi 扫不到 AP 的三连坑：① mainline brcmfmac 抢 BCM43752 SDIO（先 bind func1、
  `HT Avail timeout` 污染芯片）→ 关 `CONFIG_BRCMFMAC`；② 缺 CLM blob → `set
  country failed -2` → 无可用信道；③ OOT bcmdhd 固件路径默认 `/vendor/etc/
  firmware/`（Android）→ `modprobe.d` 传 `firmware_path` 改 `/lib/firmware/brcm/`。
- OOT bcmdhd 编译别用仓里 `bcmdhd_sdio` target（内部 `M=$(PWD)` 在容器里指错
  到 `/workspace`）→ 直接 `make -C {kernel_src} M=.../bcmdhd modules`。
