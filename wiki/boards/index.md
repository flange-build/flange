---
title: 板级索引
type: index
updated: 2026-05-10
---

# 板级索引

每块板由 `components/board/<name>/config.py` 定义，遵循三层继承（platform → SoC → board）。

- [[radxa-zero3w]] — 首个打样板，RK3566
- [[tspi-rk3566]] — RK3566
- [[neons-core3566-nanob]] — RK3566
- [[orangepi-cm4]] — RK3566
- [[rp-pro-rk3568-h]] — RK3568（首颗真 RK3568，AP6275P PCIe WiFi6/BT5.2，status: wip）
- [[radxa-cubie-a7z]] — A733（status: wip）
- [[radxa-rock5b]] — RK3588（首颗 RK3588 板，status: wip）
- [[orangepi-5-plus]] — RK3588（第二块 RK3588 板，复用 rock5b 模板 + RTL8852BE WiFi/BT，status: wip）
- [[orangepi-cm5-tablet]] — RK3588S（首块原生 RK3588S 实板，AP6256 in-tree bcmdhd 复用 cm4 路径，status: wip）
- [[khadas-vim3l]] — S905D3（首颗 Amlogic 板，AP6398S WiFi/BT，status: wip）
