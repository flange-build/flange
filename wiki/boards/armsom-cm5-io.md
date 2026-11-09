---
title: armsom-cm5-io
type: board
status: wip
sources:
  - components/board/armsom-cm5-io/config.jsonnet
  - components/board/armsom-cm5-io/patches/kernel/0001-dts-armsom-cm5-wifi-chip-ap6275s.patch
  - components/board/armsom-cm5-io/patches/kernel/0002-dts-armsom-cm5-io-drop-work-led-on-fusb302-int.patch
  - components/board/armsom-cm5-io/overlay/etc/modprobe.d/bcmdhd.conf
  - components/platform/rockchip/rk3576/config.jsonnet
  - docs/first-steps.md
related:
  - "[[rockchip 平台]]"
  - "[[radxa-rock5b]]"
  - "[[orangepi-cm4]]"
updated: 2026-09-29
---

> 阅读前提：先完成[初学指南](../../docs/first-steps.md)的环境准备，运行
> `flange target list armsom-cm5-io` 确认当前目标，再按该型号硬件说明匹配介质、接口与下载模式。
> 本页是配置摘要与硬件记录；下文验收只覆盖记录的版本、产品和测试项，不代表当前全部组合已实测。
> [返回板卡索引](index.md) · [构建与刷写流程](../workflows/lunch-build-flash-流程.md)

## TL;DR

ArmSoM CM5 IO，首颗 **RK3576**（4×A72+4×A53，Mali-G52）板。打通 RK3576 平台
构建链：可构建、可启动、GPU 走 **mainline panfrost** 开源驱动。实测启动成功、
panfrost 渲染（GLES 3.1）通过。

## 关键设计要点

- **SoC 层对齐 rk3588**：`rk3576/config.jsonnet` 复用同一 argon BSP
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
  （BCM43752/≈AP6275S）。WiFi 走 **rkwifibt OOT bcmdhd**——`kernel.config` 关内建
  `CONFIG_BCMDHD`+`CONFIG_BRCMFMAC`、`+oot_modules` 编 OOT `bcmdhd.ko`（对齐
  rock5b 模式）；固件含关键 `clm_bcm43752a2_ag.blob` 从 rkwifibt 仓
  （`firmware/broadcom/AP6275S`）部署到 `/lib/firmware/brcm/`；overlay
  `modprobe.d/bcmdhd.conf` 用 `firmware_path` 覆盖 OOT 默认 Android 路径。实测
  country CN、扫到 2.4G+5G AP。BT(UART4) 固件就绪、不预装用户态栈。
- **USB-A（4 口，排查中）**：IO 板 RTS5411S USB3 hub 上行接 SoC USB3_OTG1
  （ComboPHY1 `combphy1_psu` + USB2 `u2phy1`，`usb_drd1_dwc3` host）；hub 由常开
  VCC5V0_DEVICE_S0 供电、无 SoC 复位脚；口上 VBUS 由两颗 LPW5202 提供，EN 为 IO
  板 `USB3_HOST_PWREN_H` ← CM5 pin49（SAI1_SDO1_M0）= **GPIO4_B0**，对应 dts
  `vcc5v0_host`。按 CM5 / CM5-IO V1.1 原理图逐项核对 dts、最终 dtb 与 `.config`
  （DWC3 / XHCI / NANENG combphy / USB_STORAGE 均 `=y`），与 Armbian rkr5.1、
  mainline 写法一致；但实板插 U 盘完全无反应，根因待实板诊断（`23400000.usb`
  是否绑定、`lsusb` 是否见 `0bda:5411` / `0bda:0411`、口上 VBUS 是否 5V）。IO 板
  V1.0 的 hub OTG1_SSTX/SSRX 接反（V1.1 修正），只会退化到 USB2，不会完全无反应。

## 易踩坑

- `CONFIG_SPL_OPTEE=y` 会拉 armv7 `spl_optee.S`，arm64 SPL 编不过——OP-TEE 打包
  靠 `0006` 取消注释 `gen_bl32_node`，不靠该符号。
- WiFi 扫不到 AP 的三连坑：① mainline brcmfmac 抢 BCM43752 SDIO（先 bind func1、
  `HT Avail timeout` 污染芯片）→ 关 `CONFIG_BRCMFMAC`；② 缺 CLM blob → `set
  country failed -2` → 无可用信道；③ OOT bcmdhd 固件路径默认 `/vendor/etc/
  firmware/`（Android）→ `modprobe.d` 传 `firmware_path` 改 `/lib/firmware/brcm/`。
- OOT bcmdhd 编译别用仓里 `bcmdhd_sdio` target（内部 `M=$(PWD)` 在容器里指错
  到 `/workspace`）→ 直接 `make -C {kernel_src} M=.../bcmdhd modules`。
- BSP dts 的 `work_led`（gpio-leds，heartbeat）配在 **GPIO0_B4**，而该脚是
  FUSB302 中断 `USBCC_INT_L`：heartbeat 推挽翻转会与 FUSB302 争电平、在 LED
  拉低时误触发中断，Type-C（OTG0 / adb / DP altmode）不可靠。板级 kernel patch
  `0002` 删除该节点。本板**没有 SoC 可控的用户 LED**：IO 板 LED2 是 VCC_3V3_S0
  直驱的电源灯，`LED_GREEN_EN` / `LED_RED_EN`（GPIO2_D0 / GPIO2_D1）只引到 40pin
  排针 18 / 16 脚——别照 mainline 把 LED 挪到这两脚，否则 heartbeat 会翻转排针。
