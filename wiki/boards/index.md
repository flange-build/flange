---
title: 板级索引
type: index
updated: 2026-05-28
---

# 板级索引

每块板由 `components/board/<name>/config.py` 定义，遵循三层继承（platform → SoC → board）。

- [[radxa-zero3w]] — 首个打样板，RK3566
- [[tspi-rk3566]] — RK3566
- [[neons-core3566-nanob]] — RK3566
- [[orangepi-cm4]] — RK3566
- [[rp-pro-rk3568-h]] — RK3568（首颗真 RK3568，AP6275P PCIe WiFi6/BT5.2，status: wip）
- [[radxa-cubie-a7z]] — A733（首块 A733，ST7789V SPI 小屏 + AIC8800 USB，status: wip）
- [[radxa-cubie-a7a]] — A733（A7 家族主线板，AXP318 + AC101B 直挂 + DSI/HDMI，沿用 a7z AIC8800 USB，status: wip）
- [[radxa-rock5b]] — RK3588（首颗 RK3588 板，status: wip）
- [[orangepi-5-plus]] — RK3588（第二块 RK3588 板，复用 rock5b 模板 + RTL8852BE WiFi/BT，status: wip）
- [[orangepi-cm5-tablet]] — RK3588S（首块原生 RK3588S 实板，AP6256 in-tree bcmdhd 复用 cm4 路径，status: wip）
- [[khadas-vim3l]] — S905D3（首颗 Amlogic 板，AP6398S WiFi/BT，status: wip）
- [[radxa-zero]] — S905Y2（第二块 Amlogic 板，G12A，AW-CM256SM WiFi/BT，关 recovery，macOS host，status: wip）
- [[radxa-dragon-q6a]] — QCS6490（首颗 Qualcomm 板，UEFI/GRUB + UFS 4K LBA + Adreno 643 freedreno + AIC8800 USB，status: wip）
