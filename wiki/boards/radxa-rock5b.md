---
title: radxa-rock5b
type: board
status: wip
sources:
  - components/board/radxa-rock5b/config.py
  - components/board/radxa-rock5b/dtso/rk3588-rock-5b-mali-valhall-compat.dtso
  - components/board/radxa-rock5b/overlay/etc/hostname
  - components/board/radxa-rock5b/overlay/etc/usbdevice.conf
  - components/platform/rockchip/rk3588/config.py
related:
  - "[[rockchip 平台]]"
  - "[[out-of-tree 模块]]"
  - "[[lunch-build-flash 流程]]"
  - "[[新增板级支持]]"
updated: 2026-05-06
---

## TL;DR

Radxa ROCK 5B，RK3588 SoC（4×A76 + 4×A55），项目首块 RK3588 适配板。已落地：eMMC 启动 + UART2 串口 + GbE/SSH + GPU（mainline panthor）+ M.2 E-Key RTL8852BE WiFi6/BT。HDMI / NPU / VPU / NVMe 不在范围。

## product / variant

继承平台默认：`products: [default]`，`variants: [debug, release]`。

```
lunch radxa-rock5b-default-debug
lunch radxa-rock5b-default-release
```

## 关键差异点

| 项 | 值 |
|---|---|
| SoC | RK3588（首颗，BSP 分支 `linux-6.1-stan-rkr5.1`；rkr4.1-buildroot 的 mali_kbase 在 r0p0 silicon 上 RCU stall，必须 rkr5+） |
| DTB | `rk3588-rock-5b` |
| u-boot 分支 | `radxa/u-boot @ next-dev-v2024.10`（RK3566/RK3588 全平台统一） |
| u-boot defconfig | `rk3588_defconfig`（沿用 SoC generic，走 extlinux.conf；不用 board-specific 因其内置 androidboot 风格 bootargs 绕过 extlinux） |
| GPU | mainline panthor（rkr5.1 dts 已 `arm,mali-valhall-csf`，SoC fragment 关 mali_kbase 启 panthor）；emergency rollback overlay 在板私有 dtso |
| 调试串口 | UART2，1500000 bps（与 RK3566 一致） |
| mkimage chip | `rk3588`（同 die RK3588S 共用） |
| 分区布局 | 沿用 RK3566 5 分区（idbloader/uboot/boot/recovery/rootfs） |

## WiFi / BT

M.2 E-Key 槽位（`pcie2x1l0`，dts 默认 okay，PCIe ID `10ec:b852`）走 RTL8852BE PCIe WiFi6 + USB BT 5.2 combo。in-tree rtw89 不含 8852BE 子驱动（mainline 6.2 才进，rkr5.1 没回移），改走 [[out-of-tree 模块]]：

- `kernel.oot_sources.rkwifibt`：`radxa/rkwifibt @ develop` —— vendor 私有 stack 不依赖 mac80211
- `+oot_modules` 编 `drivers/rtl8852be` → `8852be.ko`（默认 `CONFIG_RTL8852B=y` + `CONFIG_PCI_HCI=y`，无需额外 make 参数）
- BT 走 in-tree btusb（rockchip_linux_defconfig 已 `BT_HCIBTUSB=y` + `BT_HCIBTUSB_RTL=y`）+ `+rootfs.extra_firmware` `source: oot:rkwifibt` 复用同源拷 `rtl8852bu_fw.bin` / `rtl8852bu_config.bin` 到 `/lib/firmware/rtl_bt/`

## 板私有 overlay

- `dtso/rk3588-rock-5b-mali-valhall-compat.dtso` — emergency rollback：把 GPU compatible 改回 `arm,mali-valhall` 让 BSP mali_kbase 能绑（panthor 起不来时手改 extlinux 启用）
- `overlay/etc/hostname`、`overlay/etc/usbdevice.conf`（USB gadget group=rockchip，与 zero3w 同模板）
