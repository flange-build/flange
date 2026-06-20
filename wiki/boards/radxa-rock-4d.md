---
title: radxa-rock-4d
type: board
status: wip
sources:
  - components/board/radxa-rock-4d/config.py
  - components/platform/rockchip/rk3576/config.py
  - builder/platforms/rockchip/bootloader.py
  - builder/platforms/rockchip/image.py
  - builder/flash.py
  - builder/source.py
related:
  - "[[rockchip 平台]]"
  - "[[lunch-build-flash 流程]]"
  - "[[新增板级支持]]"
updated: 2026-06-20
---

## TL;DR

Radxa ROCK 4D，RK3576（4×A72+4×A53，Mali-G52），项目首块 RK3576 板、Rockchip
首次落地 **UFS**。架构 A2：bootloader 全在 SPI NOR（锁 radxa 官方预编 spi.img）、
UFS 纯做 OS。目标：UFS 启动 + UART0 + SSH + AIC8800D80 WiFi/BT。

## 关键配置

| 维度 | 取值 | 说明 |
|---|---|---|
| SoC / dts | rk3576 / `rk3576-rock-4d` | rkr5.1 已含，`&ufs okay` |
| bootloader | **prebuilt SPI**（`prebuilt_spi_image={url,sha256}`） | 锁官方 spi.img、不自编（见下） |
| 存储 | UFS，`sector_size=4096` | board 整块覆盖 `partitions`；SoC 仍 512B |
| WiFi/BT | AIC8800D80 USB | radxa-pkg/aic8800 OOT，同 rock5c-lite |
| 串口 / root | UART0 1500000 / `1234` | 沿用 SoC；开发期 root |

## bootloader：为何锁官方预编 spi.img

flange 自编 u-boot **6 次上板全崩**在读 UFS（link up gear3 但 SCSI 数据不回、GPT
拿内存残渣 → Synchronous Abort）。根因（构建链路审计坐实）：**RK3576 的 idbloader
必须用 `boot_merger` 装配（含 `rk3576_boost`）**，flange 通用 `mkimage -T rksd`
路径缺该组件 —— RK35xx 里 RK3576 唯一不走 mkimage。与 BL31 / OPTEE / u-boot 分支
/ python2 shebang 均**无关**（逐一证伪）。

故 `prebuilt_spi_image` 构建期从 radxa 官方下载（`ensure_prebuilt_image` 校验缓存、
不入库），`bootloader.py` 只产 DB 用 miniloader。**自编为 future work**：复刻
boot_merger + `rk3576_boost` 替掉 mkimage（详见 design Decision 6）。

## UFS 4K 扇区与刷写

内核侧零改动。框架按 `partitions.sector_size` 参数化（缺省 512）：`image.py` 4K
走 `losetup -b 4096`+parted、rootfs Type-UUID 伪装 EFI System；UFS 刷写走
`flash_whole_disk`（`upgrade_tool di -p`，loader 按设备 LBA 建 GPT；实测设备报
512 逻辑块）。

## 验收（上板，follow-up）

`flange build` → `flange flash`（WL spi.img + di -p UFS）→ 串口看 U-Boot 枚举
UFS → 挂 rootfs + SSH → WiFi/BT。上板验证为 follow-up（tasks §4/§6）。
