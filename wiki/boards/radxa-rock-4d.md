---
title: radxa-rock-4d
type: board
status: wip
sources:
  - components/board/radxa-rock-4d/config.py
  - components/platform/rockchip/rk3576/config.py
  - builder/platforms/rockchip/bootloader.py
  - builder/base.py
  - docker/Dockerfile
  - builder/platforms/rockchip/image.py
  - builder/flash.py
  - builder/source.py
related:
  - "[[rockchip 平台]]"
  - "[[lunch-build-flash 流程]]"
  - "[[新增板级支持]]"
updated: 2026-06-22
---

## TL;DR

Radxa ROCK 4D，RK3576（4×A72+4×A53，Mali-G52），项目首块 RK3576 板、Rockchip
首次落地 **UFS**。架构 A2：bootloader 全在 SPI NOR（flange 自编 spi.img，关键须用
gcc-10 编 u-boot）、UFS 纯做 OS。目标：UFS 启动 + UART0 + SSH + AIC8800D80 WiFi/BT。

## 关键配置

| 维度 | 取值 | 说明 |
|---|---|---|
| SoC / dts | rk3576 / `rk3576-rock-4d` | rkr5.1 已含，`&ufs okay` |
| bootloader | **自编 SPI**（boot_merger + gcc-10） | 自编 idbloader+u-boot.itb，关键须 gcc-10（见下） |
| 存储 | UFS，`sector_size=4096` | board 整块覆盖 `partitions`；SoC 仍 512B |
| WiFi/BT | AIC8800D80 USB | radxa-pkg/aic8800 OOT，同 rock5c-lite |
| 串口 / root | UART0 1500000 / `1234` | 沿用 SoC；开发期 root |

## bootloader：自编 spi.img（关键 = gcc-10）

flange 自编可引导 UFS 的 spi.img（`flash_spi_loader=True` → `build_spi_image` 合成
idbloader@32KiB + u-boot.itb@8MiB）：idbloader 走 `boot_merger`（rkbin DDR/boost +
自编 SPL）；proper 用对板 `rock-4d-spi-rk3576_defconfig`（DT=rk3576-rock-4d-spi）；
OP-TEE 经平台 `0006` patch 进 FIT；BL31 v1.24；u-boot 分支 `next-dev-v2026.01`。

**真因（逐次上板 + 反汇编坐实）= 工具链**：老 rockchip u-boot 在 Ubuntu 24.04 默认
`gcc-13` 下整体二进制布局变化 → 开机 malloc 的 UFS GPT 读 buffer 落到 RK3576 UFS DMA
写不进的坏物理地址 → proper 读残渣崩。须用 `gcc-10`（已设全平台默认：`base.py`
`ComponentBuilder.CROSS` + `docker/Dockerfile` 装 kernel.org gcc-10.5）。`ufs.c` 汇编两
gcc 逐指令一致——非局部 miscompile，是布局效应。OP-TEE/BL31/DDR/分支/cfdab2f 均证伪。
详见 openspec `selfbuild-rk3576-spi-image`。

## UFS 4K 扇区与刷写

内核侧零改动。框架按 `partitions.sector_size` 参数化（缺省 512）：`image.py` 4K
走 `losetup -b 4096`+parted、rootfs Type-UUID 伪装 EFI System；UFS 刷写走
`flash_whole_disk`（`upgrade_tool di -p`，loader 按设备 LBA 建 GPT；实测设备报
512 逻辑块）。

## 验收

**2026-06-20 上板全通**：刷写（WL spi.img + `di -p` UFS）→ U-Boot 枚举 UFS → rootfs 挂载
+ SSH → AIC8800D80 WiFi/BT 可用。§4 `flange build` 全链路校验（4K GPT + 512 回归）
为 follow-up（tasks §4）。
