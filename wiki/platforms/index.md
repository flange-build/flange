---
title: 平台索引
type: index
updated: 2026-09-05
---

# 平台索引

每个平台对应一组 SoC 与启动/刷写策略。先查[板卡索引](../boards/index.md)确认具体型号和介质；
平台能力不代表每个 board/product/variant 已完成当前版本实机验收。

- [rockchip 平台](rockchip-平台.md) — RK 系列，已落地 RK3506B / RK3566 / RK3568 / RK3576 / RK3588 / RK3588S；刷写 upgrade_tool
- [allwinnera733 平台](allwinnera733-平台.md) — A733 进行中；刷写 dd（FEL / PhoenixSuit 待实现）
- [amlogic 平台](amlogic-平台.md) — S905Y2 / A311D / S905D3；刷写 pyamlboot + fastboot 两段式
- [qualcommqcs6490 平台](qualcommqcs6490-平台.md) — QCS6490 (SC7280-class) 进行中；首个 UEFI/GRUB 平台；刷写 edl-ng (EDL 9008)
- [qualcommsc8280xp 平台](qualcommsc8280xp-平台.md) — SC8280XP；复用 Qualcomm UEFI/GRUB 与 edl-ng 策略
