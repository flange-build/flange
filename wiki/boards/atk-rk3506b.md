---
title: atk-rk3506b
type: board
status: stable
sources:
  - components/board/atk-rk3506b/config.py
  - components/board/atk-rk3506b/patches/kernel/
  - components/platform/rockchip/rk3506b/config.py
  - builder/platforms/rockchip/amp.py
  - docs/boards/atk-rk3506b.md
  - components/packages/cardputer-all-in-one/README.md
  - openspec/specs/rockchip-atk-rk3506b/spec.md
  - openspec/changes/add-rk3506-fluxion-foc-amp/
related:
  - "[[rockchip 平台]]"
  - "[[amp 构建器]]"
  - "[[AMP 协处理器与 rpmsg]]"
  - "[[rk3506 AMP UART4 RPMsg demo]]"
  - "[[Cardputer USB 复合设备]]"
updated: 2026-08-24
---

## TL;DR

正点原子 ATK-RK3506B：512 MiB DDR + 512 MiB SPI NAND，flange 首块 ARM32、UBI/UBIFS 和 vendor FIT Rockchip 板。Linux 占 CPU0-1，CPU2 运行 RT-Thread AMP 固件。

## 当前契约

| 项 | 实现 |
|---|---|
| kernel | Linux 6.1，ARM `zImage`，gcc-10.3.1 |
| rootfs | Ubuntu Base 24.04 armhf，`rootfs.ubi` |
| 刷写 | Maskrom + `upgrade_tool`，parameter + 具名 `DI`，不生成 GPT `raw.img` |
| AMP | CPU2 `0x03e00000`，UART4 + RPMsg `0x3003` |
| 网络 | 2× YT8512C 100M；RTL8733BUUA USB Wi-Fi/BT |
| USB host | Cardputer GUD/HID/UAC1 与在线音乐播放器 |

上述启动、UBIFS 可写、双网口、Wi-Fi、Cardputer 显示/键盘/音频、UART4 和 RPMsg echo 都有实机验收。

## product

`default` 保留 UART4/RPMsg echo 救援基线。`fluxion` 改用仓库外 `fluxion_runtime` AMP App；板级 patch 把 SPI0 PWM、I2C1/AS5600、时钟和 IRQ 73 交给 CPU2。完整镜像已通过构建门禁，真实功率级、快环时序与故障注入仍待实板验收。
