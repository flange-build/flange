---
title: neons-core3566-nanob
type: board
status: stable
sources:
  - components/board/neons-core3566-nanob/config.jsonnet
  - components/board/neons-core3566-nanob/overlay/etc/hostname
  - docs/first-steps.md
related:
  - "[[rockchip 平台]]"
  - "[[lunch-build-flash 流程]]"
  - "[[新增板级支持]]"
updated: 2026-09-05
---

> 阅读前提：先完成[初学指南](../../docs/first-steps.md)的环境准备，运行
> `flange target list neons-core3566-nanob` 确认当前目标，再按该型号硬件说明匹配介质、接口与下载模式。
> 本页是配置摘要与硬件记录；下文验收只覆盖记录的版本、产品和测试项，不代表当前全部组合已实测。
> [返回板卡索引](index.md) · [构建与刷写流程](../workflows/lunch-build-flash-流程.md)

## TL;DR

Neons Core3566 Nano B，RK3566 核心板 + Waveshare CM4 底板方案，无板载 WiFi，overlay 最简。

## product / variant

继承平台默认：`products: [default]`，`variants: [debug, release]`。

```
lunch neons-core3566-nanob-default-debug
lunch neons-core3566-nanob-default-release
```

## 关键差异点

| 项 | 值 |
|---|---|
| DTB | `rk3566-neons-core-wavesharecm4-nano-b` |
| kernel commit | `e62b45ad`（锁定版本） |
| bootloader commit | `3c60a711`（同 tspi-rk3566） |
| patches | 无 |

kernel 与 bootloader 均锁定到特定 commit，确保与 Waveshare CM4 底板硬件兼容性。

## overlay

仅 `overlay/etc/hostname`，无 `usbdevice.conf`（USB gadget 配置使用平台默认）。
