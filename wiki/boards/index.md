---
title: 板级索引
type: index
updated: 2026-09-06
---

# 板级索引

每块板由 `components/board/<name>/config.jsonnet` 定义，叠加公共基线与 platform → SoC → board 硬件层。

先完成[初学指南](../../docs/first-steps.md)的宿主准备，再阅读对应板卡页。
这些页面是配置摘要和历史硬件记录；状态与已通过项只覆盖页面标明的目标、版本和介质。
产品列表以 `flange target list <board>` 为准，首次接线/下载模式须对照该型号硬件说明。

- [radxa-zero3w](radxa-zero3w.md) — 首个打样板，RK3566
- [tspi-rk3566](tspi-rk3566.md) — RK3566
- [neons-core3566-nanob](neons-core3566-nanob.md) — RK3566
- [orangepi-cm4](orangepi-cm4.md) — RK3566
- [atk-rk3506b](atk-rk3506b.md) — RK3506B（ARM32，SPI NAND/UBI + CPU2 RT-Thread + Cardputer GUD/HID/UAC，status: stable）
- [rp-pro-rk3568-h](rp-pro-rk3568-h.md) — RK3568（首颗真 RK3568，AP6275P PCIe WiFi6/BT5.2，status: wip）
- [armsom-cm5-io](armsom-cm5-io.md) — RK3576（首颗 RK3576，Mali-G52 panfrost 开源 GPU，OP-TEE 打包，BW3752/AP6275S WiFi/BT，status: wip）
- [radxa-rock-4d](radxa-rock-4d.md) — RK3576（首块 UFS 4K 存储板，image/flash 扇区参数化，UFS 启动 + SSH + WiFi/BT 上板通，status: done）
- [radxa-cubie-a7z](radxa-cubie-a7z.md) — A733（首块 A733，ST7789V SPI 小屏 + AIC8800 USB，status: wip）
- [radxa-cubie-a7a](radxa-cubie-a7a.md) — A733（A7 家族主线板，AXP318 + AC101B 直挂 + DSI/HDMI，沿用 a7z AIC8800 USB，status: wip）
- [radxa-rock5b](radxa-rock5b.md) — RK3588（首颗 RK3588 板，status: wip）
- [orangepi-5-plus](orangepi-5-plus.md) — RK3588（第二块 RK3588 板，复用 rock5b 模板 + RTL8852BE WiFi/BT，status: wip）
- [orangepi-cm5-tablet](orangepi-cm5-tablet.md) — RK3588S（首块原生 RK3588S 实板，AP6256 in-tree bcmdhd 复用 cm4 路径，status: wip）
- [khadas-vim3](khadas-vim3.md) — A311D（G12B，AP6398S WiFi/BT，软件配置就绪、待实板验收）
- [khadas-vim3l](khadas-vim3l.md) — S905D3（首颗 Amlogic 板，AP6398S WiFi/BT，status: wip）
- [radxa-zero](radxa-zero.md) — S905Y2（第二块 Amlogic 板，G12A，AW-CM256SM WiFi/BT，关 recovery，macOS host，status: wip）
- [radxa-dragon-q6a](radxa-dragon-q6a.md) — QCS6490（首颗 Qualcomm 板，UEFI/GRUB + UFS 4K LBA + Adreno 643 freedreno + AIC8800 USB，status: wip）
- [radxa-dragon-q8b](radxa-dragon-q8b.md) — SC8280XP（UEFI/GRUB + UFS 4K LBA + Adreno/MSM + QPS615/TC956x 双网口，status: wip）

- [radxa-rock5c-lite](radxa-rock5c-lite.md) — RK3582，含 USB-C OTG 与 LCD HAT 专题。
