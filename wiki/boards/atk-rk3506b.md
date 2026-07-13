---
title: atk-rk3506b
type: board
status: stable
sources:
  - components/board/atk-rk3506b/config.py
  - components/board/atk-rk3506b/patches/bootloader/0001-add-alientek-rk3506-board.patch
  - components/board/atk-rk3506b/patches/bootloader/0002-fix-vendor-fit-bootdev.patch
  - components/board/atk-rk3506b/patches/kernel/0001-reserve-amp-firmware-memory.patch
  - components/platform/rockchip/rk3506b/config.py
  - docs/boards/atk-rk3506b.md
  - openspec/changes/add-rk3506b-atk-rk3506b/evidence/rk3506b-hardware-acceptance.md
related:
  - "[[rockchip 平台]]"
  - "[[amp 构建器]]"
  - "[[AMP 协处理器与 rpmsg]]"
  - "[[FlashStrategy 抽象]]"
  - "[[rk3506 AMP UART4 RPMsg demo]]"
updated: 2026-07-14
---

## TL;DR

正点原子 ATK-RK3506B：512 MiB DDR + 512 MiB SPI NAND，flange 首块 ARM32、UBI/UBIFS、vendor FIT Rockchip 板。Linux 占 CPU0-1，CPU2 跑最小 RT-Thread；全量刷写、断电冷启动、UBIFS 可写与 ADB 已实机通过。

## 配置

| 项 | 值 |
|---|---|
| kernel | `linux-6.1-stan-rkr5.1`，ARM `zImage`，gcc-10.3.1 |
| DTS | `rk3506b-alientek-mipi720x1280-nand-ubi-ubifs-amp-linux` |
| boot | `boot.img` vendor FIT；启动参数取 DTS `chosen.bootargs` |
| rootfs | Ubuntu Base 24.04 armhf，`rootfs.ubi`，`ubi0:rootfs` |
| AMP | CPU2 `0x03e00000`，UART4 1500000 8N1，RPMsg `0x3003` |

分区顺序固定为 `idbloader → uboot → boot → recovery(1 MiB 占位) → amp → rootfs`，因此 rootfs 始终是 `mtd5`。SPI NAND 不生成 GPT `raw.img`；构建期由配置生成 `parameter.txt`，刷写走 `UL -noreset`、`DI -p` 与具名 `DI`，不调用该 loader 不支持的 `SSD`。

## 实机状态（2026-07-14）

- `flange flash` 从 Maskrom 全刷成功，断电后进入 Linux 6.1.115；`/` 为可写 UBIFS。
- `/sys/devices/system/cpu/online` 为 `0-1`；`/proc/iomem` 排除 `0x03b00000-0x03efffff`，不会覆盖 AMP 共享区与 CPU2 固件。
- RPMsg channel 已枚举；USB gadget 自动加载模块并绑定 `ff740000.usb`，ADB 可直接进入。
- UART4/MSH 输出、RPMsg 多轮二进制 echo、坏块/恢复演练仍是后续验收项。
