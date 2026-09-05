---
title: radxa-zero3w
type: board
status: stable
sources:
  - components/board/radxa-zero3w/config.jsonnet
  - components/platform/rockchip/config.jsonnet
  - docs/development-guide.md
  - components/board/radxa-zero3w/overlay/etc/hostname
  - components/board/radxa-zero3w/overlay/etc/usbdevice.conf
  - docs/first-steps.md
related:
  - "[[rockchip 平台]]"
  - "[[lunch-build-flash 流程]]"
  - "[[新增板级支持]]"
updated: 2026-09-05
---

> 阅读前提：先完成[初学指南](../../docs/first-steps.md)的环境准备，运行
> `flange target list radxa-zero3w` 确认当前目标，再按该型号硬件说明匹配介质、接口与下载模式。
> 本页是配置摘要与硬件记录；下文验收只覆盖记录的版本、产品和测试项，不代表当前全部组合已实测。
> [返回板卡索引](index.md) · [构建与刷写流程](../workflows/lunch-build-flash-流程.md)

## TL;DR

Radxa Zero 3W，RK3566 SoC，WiFi/BT 板型（802.11ac + BT5），项目首个打样验证目标。历史记录称构建与刷写流程跑通；本页未提供当前 commit 的逐项实机验收。

## product / variant

当前板级配置声明 `products: [default, desktop]`，`variants: [debug, release]`。
`desktop` 额外启用 `ubuntu-desktop` Package，四种完整目标可用 `flange target list radxa-zero3w` 查看。

选择示例：

```
flange target select radxa-zero3w-default-debug
flange --target radxa-zero3w-desktop-release plan image
```

## 构建与首次接板前

当前继承的内核来源使用 Git SSH 地址 `ssh://git@github.com/flange-build/kernel.git`。
首次构建需要可用的 Git SSH 凭据，源码定义以[平台配置](../../components/platform/rockchip/config.jsonnet)
和 `flange target show` 为准；工作区、Docker、大小写敏感输出卷准备见[开发指南](../../docs/development-guide.md)。

接口位置、供电与 Maskrom 操作请对照
[Radxa ZERO 3 官方准备说明](https://docs.radxa.com/en/zero/zero3/getting-started/preparation)和
[ZERO 3W eMMC / Maskrom 图示](https://docs.radxa.com/zero/zero3/low-level-dev/install-os-on-emmc)
（2026-09-05 核对）。官方发行版刷写示例的镜像与账号不能直接代替 flange 的产物与配置。

构建成功后先 `flange status`、`flange flash --list`，确认目标和分区；普通 GPT 更新启动内容使用
清单中的 `boot` 分区。完整操作路径见[构建与刷写流程](../workflows/lunch-build-flash-流程.md)。

## 关键差异点

| 项 | 值 |
|---|---|
| DTB | `rk3566-radxa-zero-3w` |
| kernel patches | 无（使用平台/SoC 默认） |
| board patches | 无 |

## overlay

`overlay/etc/hostname` — 设备主机名；`overlay/etc/usbdevice.conf` — USB gadget 配置（ADB/串口）。其余均走平台默认。
