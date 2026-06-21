---
title: qualcommqrb2210 平台
type: platform
status: wip
sources:
  - builder/platforms/qualcommqrb2210/__init__.py
  - builder/platforms/qualcommqrb2210/kernel.py
  - builder/platforms/qualcommqrb2210/bootloader.py
  - builder/platforms/qualcommqrb2210/rootfs.py
  - builder/platforms/qualcommqrb2210/boot.py
  - builder/platforms/qualcommqrb2210/recovery.py
  - builder/platforms/qualcommqrb2210/image.py
  - components/platform/qualcommqrb2210/config.py
  - components/platform/qualcommqrb2210/qrb2210/config.py
  - builder/flash.py#QualcommQrb2210FlashStrategy
  - openspec/changes/add-qrb2210-arduino-uno-q/
related:
  - "[[arduino-uno-q]]"
  - "[[qualcommqcs6490 平台]]"
  - "[[FlashStrategy 抽象]]"
  - "[[USB 线刷协议]]"
updated: 2026-06-21
---

## TL;DR

flange 第二个 Qualcomm 平台。QRB2210 / QCM2290（Dragonwing，代号 Imola/Agatti）—
Adreno 702 + 4× A53。与 [[qualcommqcs6490 平台]]（UEFI/GRUB）不同，本平台落在
**U-Boot extlinux 世界**：启动链 `PBL→XBL→TZ/HYP→ABL→U-Boot→extlinux→Linux`，
U-Boot 是 ABL 链加载的 Android boot.img，经 `sysboot`（= extlinux）引导内核。
刷写走 **qdl**（apt 可装，EDL 9008），EDL 经 **JCTL 跳线**进入。内核走
**mainline Linux v7.0**（`qrb2210-arduino-imola.dts` 已上游进 7.0）。

> ⚠️ 本平台尚未实板 bring-up。配置/构建器/刷写策略已落地并经 Python 级验证
> （registry 自动发现、lunch target、builder 实例化、flash 策略注册）；
> Docker 编译、vendor 固件包、实板启动均待验证。详见 openspec change
> `add-qrb2210-arduino-uno-q` 的 tasks.md。

## 与 Q6A 的关键差异

同为 Qualcomm，但 UNO Q 与 Q6A 是两种高通形态：

| 维度 | qualcommqcs6490 (Q6A) | qualcommqrb2210 (UNO Q) |
|------|---|---|
| 引导链 | UEFI → GRUB(grub-with-dtb) → kernel | ABL → U-Boot → **extlinux/sysboot** → kernel |
| boot 组件 | `grub-mkimage` BOOTAA64.EFI + ESP(FAT) | `builder/extlinux.py` extlinux.conf + boot.img(ext4) |
| bootloader 介质 | **独立 SPI NOR**（XBL/EDK2） | 与 OS **同一块 eMMC** 固定 vendor GPT |
| 内核 | radxa/kernel@linux-7.0.2 | **mainline Linux v7.0** + qrb2210-arduino-imola.dtb |
| 系统盘 | UFS（4096 字节 LBA） | eMMC（512 字节扇区） |
| image | 整盘 raw.img（write-sector 0 重建 GPT） | **按分区** boot/rootfs，**不重建 GPT** |
| 刷写工具 | edl-ng（需手动下载） | **qdl**（`apt install qdl`） |
| flash 命令 | `edl-ng --memory UFS write-sector 0` | `qdl --allow-missing --storage emmc <rawprogram>` |
| Wi-Fi | AIC8800 USB OOT | **mainline ath10k** |
| GPU | Adreno 643 freedreno | Adreno 702 freedreno |

## 关键设计要点

**整盘 vs 按分区的真正分水岭**：不是「Q6A 整盘、UNO Q 分区」这种表面对比，而是
**bootloader 与 OS 是否共享同一块介质**。Q6A 的 bootloader 在独立 SPI NOR、OS 在
独立 UFS，故能 `write-sector 0` 在 UFS 上重建全新 2 分区 GPT。UNO Q 的 bootloader
（XBL/ABL/TZ/HYP/U-Boot）与 OS（boot/rootfs）**挤在同一块 eMMC 的固定 vendor GPT
（约 67 分区）**里，`write-sector 0` 会抹掉 vendor bootloader 分区——所以只能用
qdl rawprogram **按分区**把 boot/rootfs 写进既有槽位，`--allow-missing` 跳过 vendor 槽。

**U-Boot extlinux 复用**：U-Boot 的 `sysboot` 即 flange 原生 extlinux 模型，`boot.py`
直接复用 `builder/extlinux.py` 生成 `/extlinux/extlinux.conf` + Image + dtb，打成
boot.img（ext4）。⚠️ Armbian 用定制 `boot-qrb2210.cmd`（显式 load 地址规避 ABL
保留内存区）；v1 依赖预编 U-Boot boot.img 的 distro_bootcmd 默认地址，若实板冲突
需在 bootloader 层补平台 boot 脚本。

**bootloader 消费预编 blob**：XBL/ABL/TZ/HYP/U-Boot boot.img/GPT/firehose loader/
vendor rawprogram 由 `bootloader.py` 下载 Arduino/armbian 预编 EDL 包（armbian/qcombin
「Agatti/arduino-uno-q」），flange 不编译。bring-up 一次性经 `flange flash
--spi-firmware` 刷 vendor 槽。

**内核 mainline v7.0**：`qrb2210-arduino-imola.dts` + dt-bindings 已上游进 Linux 7.0；
Armbian edge 已从 arduino/linux-qcom fork 切到 mainline v7.0。`kernel.py` 用 arm64
通用 defconfig（含 qcom），按需 `enable_configs` 补 eMMC（SDHCI_MSM）/ GENI 串口 /
固件解压 builtin。

## 刷写（QualcommQrb2210FlashStrategy）

- 系统（每次）：`qdl --allow-missing --storage emmc --include <boot> --include <rootfs>
  <firehose> flange_rawprogram.xml` —— flange rawprogram（`image.py` 生成）仅含
  boot/rootfs 两条目。
- vendor 固件（bring-up 一次）：`flange flash --spi-firmware` → `qdl --storage emmc
  <firehose> rawprogram*.xml patch*.xml`（vendor 预编包）。
- EDL 经 **JCTL 跳线** 进入；设备枚举为 Qualcomm HS-USB QDLoader 9008（05c6:9008）。

## 待办（bring-up）

详见 openspec `add-qrb2210-arduino-uno-q` tasks.md：mainline defconfig 外设核对、
vendor rawprogram 的 boot/rootfs label/sector 校正、U-Boot load 地址验证、
Adreno 702 固件落点确认、实板启动全栈验证。
