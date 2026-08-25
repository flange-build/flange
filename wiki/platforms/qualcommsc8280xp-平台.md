---
title: qualcommsc8280xp 平台
type: platform
status: wip
sources:
  - builder/platforms/qualcommsc8280xp/__init__.py
  - components/platform/qualcommsc8280xp/config.jsonnet
  - components/platform/qualcommsc8280xp/sc8280xp/config.jsonnet
  - builder/flash.py
related:
  - "[[radxa-dragon-q8b]]"
  - "[[qualcommqcs6490 平台]]"
  - "[[FlashStrategy 抽象]]"
updated: 2026-08-24
---

## TL;DR

SC8280XP 是 flange 的第二条 Qualcomm 路线。它通过一个薄入口复用已有的
UEFI/GRUB、Ubuntu rootfs、4K UFS image 和 `edl-ng` 刷写实现，不复制六套 builder。

## 关键设计

- 内核跟随 `radxa/kernel` 的 `linux-7.0.11` 分支 HEAD，每次构建先 fetch；源 HEAD 变化会使下游缓存失效。
- UFS、QMP PHY 与 SC8280XP interconnect 保持 built-in，`DRM_MSM=m` 等 rootfs 可用后再加载显示固件。
- 平台不启用 recovery；启动链、SPI 固件、UFS 初始化与整盘刷写契约与 QCS6490 一致。
- Qualcomm kernel 使用 `.build/cache/ccache` 保留浮动分支的增量编译收益。

## 边界

当前只接入 [[radxa-dragon-q8b]]。分支 HEAD 模式便于跟进 RSDK，但不具备 commit pin 的完全可复现性；发布镜像应记录实际 HEAD。
