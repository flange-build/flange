# radxa-rock-4d

> 阅读前提：先完成[初学指南](../first-steps.md)的环境准备，运行
> `flange target list radxa-rock-4d` 确认当前目标，再按该型号硬件说明匹配介质、接口与下载模式。
> 本页是配置摘要与硬件记录；下文验收只覆盖记录的版本、产品和测试项，不代表当前全部组合已实测。
> [返回板卡索引](README.md) · [构建与刷写流程](../development-guide.md)

## 概述

Radxa ROCK 4D 使用 RK3576（4×Cortex-A72 + 4×Cortex-A53），GPU 为 Mali-G52。
当前启动固件位于 SPI NOR，UFS 承载系统分区。提供 `default/desktop` 与 `debug/release`。

## 配置与引导链

| 项目 | 当前配置 |
| --- | --- |
| 内核设备树 | `rockchip/rk3576-rock-4d.dtb` |
| U-Boot | `next-dev-v2026.01`，`rock-4d-spi-rk3576_defconfig` |
| SPI 镜像 | 自编 `spi.img`：idbloader 位于 32 KiB，u-boot.itb 位于 8 MiB |
| SPL / DDR | 同源自编 SPL，经 boot_merger 与 rkbin DDR/boost 组合 |
| UFS | 布局声明 `sector_size=4096`，不重复放置 SPI 内的引导固件 |
| Wi-Fi / 蓝牙 | AIC8800D80 USB，树外驱动与配套固件 |
| 串口 | UART0，1500000 bps |

U-Boot 使用仓库的 GCC 10 工具链。UFS 读取异常还受 SPL 的 DMA 授权约束：
混用其他源码树的预编 SPL 与自编 proper 会造成读缓冲没有数据；仅替换 GCC 版本不能保证修复。
当前装配方式和原理见 [Rockchip 引导固件约束](../boot-and-flash.md#rockchip-引导固件的配套约束)。
开发镜像显式设置 root 口令 `1234`；交付前应在产品配置中替换开发账户策略。

## 构建与刷写

```bash
lunch radxa-rock-4d-default-debug
flange build
flange flash --list
# 按工具提示进入 MaskROM 并连接 USB 后，写入 SPI 固件和系统
flange flash --spi-firmware
```

SPI 固件与 UFS 属于不同存储介质；刷写策略负责切换。不要把普通 eMMC 的裸偏移直接用于 UFS。
镜像生成采用 4 KiB 扇区布局，设备 Loader 报告的逻辑块单位可能不同；以生成清单与策略处理为准。

## 实测范围

2026-06-20 记录确认 SPI 固件写入、UFS 引导、rootfs 挂载、SSH 与 AIC8800D80 Wi-Fi/蓝牙可用。
该记录不代表此后全部产品、内核版本或外设组合已经验收；桌面、GPU/NPU 与长期 UFS 稳定性需单独验证。
