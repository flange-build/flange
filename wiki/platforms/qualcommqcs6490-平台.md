---
title: qualcommqcs6490 平台
type: platform
status: wip
sources:
  - builder/platforms/qualcommqcs6490/__init__.py
  - builder/platforms/qualcommqcs6490/kernel.py
  - builder/platforms/qualcommqcs6490/bootloader.py
  - builder/platforms/qualcommqcs6490/rootfs.py
  - builder/platforms/qualcommqcs6490/boot.py
  - builder/platforms/qualcommqcs6490/recovery.py
  - builder/platforms/qualcommqcs6490/image.py
  - components/platform/qualcommqcs6490/config.jsonnet
  - components/platform/qualcommqcs6490/qcs6490/config.jsonnet
  - components/platform/qualcommqcs6490/patches/kernel/
  - builder/flash/strategy.py#QualcommFlashStrategy
  - openspec/changes/add-qcs6490-radxa-dragon-q6a/
  - openspec/changes/archive/2026-05-31-migrate-qcs6490-kernel-702/
  - docs/development-guide.md
  - docs/extension-guide.md
related:
  - "[[radxa-dragon-q6a]]"
  - "[[qualcommsc8280xp 平台]]"
  - "[[FlashStrategy 抽象]]"
  - "[[USB 线刷协议]]"
updated: 2026-09-05
---

> 阅读前提：先读[架构总览](../concepts/架构总览.md)，并从[板卡索引](../boards/index.md)确认型号。
> 本页保留平台机制与历史适配记录；芯片支持、产物可构建和实机验收是不同边界。
> 当前操作见[开发指南](../../docs/development-guide.md)，扩展步骤见[扩展指南](../../docs/extension-guide.md)。

## 当前基线（2026-08-24）

QCS6490 已从下方建库时记录的 vendor BSP 6.6.90，历经 mainline 6.18.2，迁移到 **`radxa/kernel@linux-7.0.2`**，固定 commit `7473a9f`。内核配置按 `defconfig + qcom_module.config + radxa.config + radxa_custom.config` 四段叠加；UFS/SCSI/QMP PHY 和 interconnect 必须 built-in，因为 flange 不生成 initramfs。

当前启动与刷写边界如下：

- ESP 只存放 GRUB EFI 与菜单，kernel/DTB 位于 rootfs `/boot`；4K LBA UFS 上不在 `fstab` 挂载 ESP。
- 普通 `flange flash` 只写 UFS `raw.img`；`flange flash --spi-firmware` 单独更新 EDK2 SPI 固件。7.0.2 需要与当前 SPI 固件配套，旧固件可能在 UFS probe 阶段触发整机复位。
- 全新 UFS 先执行 `flange flash --provision-ufs lun0-only` 或 `flange flash --provision-ufs qcom` 建立 LUN 布局；该操作会清除 UFS 数据，完成后须重新进入 EDL，再执行普通全量刷写。

下方 6.6.90 内容保留为早期 bring-up 基线，其中 UEFI/GRUB、4K LBA、ESP 挂载限制和排障过程仍有参考价值；涉及“当前内核”的表述以本节和 [[radxa-dragon-q6a]] 为准。

## TL;DR

flange 首个 Qualcomm 平台。QCS6490 (SC7280-class, Dragonwing) — Adreno 643 + Hexagon ADSP/CDSP + 4× A78 + 4× A55。**Boot 链是 UEFI**（XBL→EDK2→GRUB→Linux），与其他平台 U-Boot/extlinux 路线完全不同；刷写走 **EDL/edl-ng**（USB 9008）。内核走 Qualcomm vendor BSP `kernel.qclinux.1.0.r1-rel`（6.6.90 LTS）。

## 与其他平台的关键差异

| 维度 | Rockchip / Allwinner / Amlogic | qualcommqcs6490 |
|------|---|---|
| bootloader | U-Boot 源码构建 | Radxa 预编 EDK2 SPI blob（flange 不编） |
| 引导链 | U-Boot → extlinux/FIT | UEFI → GRUB(grub-with-dtb) → kernel |
| boot 组件 | extlinux.conf / boot.img | `grub-mkimage` 生成 BOOTAA64.EFI + grub.cfg + ESP(FAT) |
| 系统盘 | eMMC/SD | UFS（4096 字节 LBA） |
| 分区 | u-boot/boot/rootfs 三件套 | ESP(FAT) + rootfs(ext4)，GPT 4K LBA |
| 刷写工具 | upgrade_tool / dd / pyamlboot | **edl-ng**（Qualcomm EDL 9008） |
| flash 整盘命令 | dd / fastboot | `edl-ng write-sector --memory UFS` |

## 关键设计要点

**UEFI/GRUB 链**：板上跑 Radxa 预编的 EDK2 BIOS（来自 `dragon-q6a_flat_build_wp_260120.zip`，烧 SPI NOR）。flange 只组装 ESP：`grub-mkimage -O arm64-efi` 把 GRUB EFI 独立化，prefix `/EFI/BOOT`；ESP 内放 `BOOTAA64.EFI` + `grub.cfg`（含 `devicetree /boot/<dtb>.dtb` + `linux /boot/vmlinuz acpi=off console=ttyMSM0,115200 root=PARTLABEL=rootfs rootwait`）。内核 Image / dtb 装在 **rootfs 的 `/boot/`**（GRUB 用 ext2 模块读 rootfs 分区）。

**4K LBA UFS**：`partitions.sector_size=4096`，`image.py` 用 `losetup -b 4096` + `parted` 让 GPT 按 4K 对齐写入。config 里 offset/size 仍以 512 扇区计，`_resolve_entries` 自动折算。

**fstab 不挂 ESP**：vfat 内核驱动在 4K LBA 上读 512-sector FAT superblock 报无效；flange 重刷模型不需要运行时挂 ESP，rootfs.py `_install_fstab` 只写 `LABEL=rootfs / ext4`，避免 boot-efi.mount fail → degraded。

**kernel baseline**：曾试 mainline 6.18 触发 UFS HS-G4 PHY 复位（缺 sc7280 7 个 PCS 寄存器 + Radxa DTS 用 `limit-gear-rate` 非 mainline 的 `limit-rate`），切到 `radxa/kernel@kernel.qclinux.1.0.r1-rel` (6.6.90)。QEMU amd64 模拟下 `jobs=2` 防 OOM（aic8800 mod 编译会撑爆容器内存）。

**已纳 patches**：
- `components/platform/qualcommqcs6490/patches/kernel/0001-dwc3-gadget-preserve-pending-requests-on-clear-stall.patch` — port 自 `bsp/kernel d77dbaa`，治 Mac host ClearFeature(ENDPOINT_HALT) 杀 adbd。
- 板级 patch 见 `[[radxa-dragon-q6a]]`。

**rootfs +packages 标配**（debug 变体多 `mesa-utils/vulkan-tools`）：mesa freedreno/turnip + linux-firmware + alsa-ucm-conf + wireless-regdb + iw + wpasupplicant。
