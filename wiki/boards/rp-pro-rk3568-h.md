---
title: rp-pro-rk3568-h
type: board
status: wip
sources:
  - components/board/rp-pro-rk3568-h/config.py
  - components/board/rp-pro-rk3568-h/patches/kernel/0001-dts-pro-rk3568-h-firmware-class-path-fix.patch
  - components/board/rp-pro-rk3568-h/patches/kernel/0002-dt-bindings-mipi-dsi-eot-packet-compat.patch
  - components/board/rp-pro-rk3568-h/overlay/etc/hostname
  - components/board/rp-pro-rk3568-h/overlay/etc/usbdevice.conf
  - components/platform/rockchip/rk3568/config.py
related:
  - "[[rockchip 平台]]"
  - "[[out-of-tree 模块]]"
  - "[[lunch-build-flash 流程]]"
  - "[[新增板级支持]]"
  - "[[GUD 屏作 X11 显示]]"
updated: 2026-06-19
---

## TL;DR

rpdzkj pro-rk3568-h，**项目首块真 RK3568 板**（dts 在 BSP `rp-rk356x/` vendor 子目录），板载 AP6275P WiFi6/BT5.2 PCIe 模组。

```
lunch rp-pro-rk3568-h-default-debug
```

## 关键差异点

| 项 | 值 |
|---|---|
| SoC | RK3568（新建 SoC 层 `rk3568/`，**不挂 rk3566**——`RK3568MINIALL.ini` 走 1560MHz DDR，`RK3566MINIALL.ini` 1056MHz，挂错砍 33% 性能） |
| DTB | `pro-rk3568-h`（`dts_dir = rockchip/rp-rk356x`） |
| WiFi/BT | AP6275P PCIe（BCM43752A2），OOT bcmdhd_pcie.ko |

## WiFi / BT

AP6275P 是 BCM43752A2 的 PCIe 版（AP6275S 才是 SDIO，rkwifibt `wifibt-util.sh` 明列），PCIe ID `14e4:449d`：

- `kernel.oot_sources.rkwifibt: radxa/rkwifibt @ develop`
- `+oot_modules` 走 kbuild 标准入口 `-C {kernel_src} M=… modules CONFIG_BCMDHD=m CONFIG_BCMDHD_PCIE=y **CONFIG_BCMDHD_SDIO=**`。最后一项必须显式清空：kbuild 进 OOT 时 source 内核 `.config` 把 `CONFIG_BCMDHD_SDIO=y`（in-tree `rkwifi/Kconfig` `choice default BCMDHD_SDIO`）当 make 变量喂入，与 PCIe 同时启用会让 `dhd_config.h` 中 `dhd_conf_get_otp` 在 SDIO 与 PCIe 两个 `#ifdef` 块各有不同签名，conflicting types
- 不走 bcmdhd Makefile 顶层 phony target（`all` 编 PCIe+SDIO+USB 三变体，且用 `LINUXDIR/$(PWD)` 与 rock5b rtl8852be 的 `KSRC/M` 约定不同）
- in-tree bcmdhd 默认 SDIO 不抢 PCI 总线，与 OOT `bcmdhd_pcie.ko` 共存无冲突
- 固件走 `+rootfs.+extra_firmware` `source: oot:rkwifibt`，从 `firmware/broadcom/AP6275_PCIE/{wifi,bt}/` 平铺到 `/lib/firmware/`：fw + clm + `nvram_ap6275p.txt`（小写，driver chip 表 module_name = `ap6275p`）+ `BCM4362A2.hcd`
- **不用 armbian/firmware**：其 `ap6275p/nvram_ap6275p.txt` 是 symlink → `nvram_AP6275P.txt`，macOS APFS 大小写不敏感致 git checkout collision，target 没物理落盘，dangling link

## kernel patches

- `0001-dts-pro-rk3568-h-firmware-class-path-fix` — 修 `pro-rk3568-h.dts:111` 的 `chosen.bootargs`：去 Android `firmware_class.path=/system/etc/firmware` → `/lib/firmware`；删硬编码 `root=PARTUUID=614e0000-0000`（让 extlinux APPEND 决定 root，与 [[tspi-rk3566]] 同模式）
- `0002-dt-bindings-mipi-dsi-eot-packet-compat` — `MIPI_DSI_MODE_EOT_PACKET` 在 mainline 5.11 (commit `4da4232c4cd5`) rename 成 `MIPI_DSI_MODE_NO_EOT_PACKET` 且反转语义，rp-rk356x BSP 25+ LCD dtsi 仍用旧名，dtc syntax error。在 `dt-bindings/display/drm_mipi_dsi.h` 末尾加 `#define MIPI_DSI_MODE_EOT_PACKET 0`（no-op，等同 6.x 默认行为发 EOT），不批量改 dtsi（机械改名会反转所有 panel EOT 行为）

## overlay

`overlay/etc/hostname` + `overlay/etc/usbdevice.conf`，与同平台其他板模板一致。
