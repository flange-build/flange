## Why

flange 已有 Qualcomm 平台 `qualcommqcs6490`（Radxa Dragon Q6A），走的是 **UEFI 世界**：PBL→XBL→EDK2 UEFI→GRUB→OS，系统盘是独立 UFS、bootloader 在独立 SPI NOR、刷写用 edl-ng `write-sector` 整盘。

Arduino UNO Q（Qualcomm Dragonwing **QRB2210 / QCM2290**，代号 Imola/Agatti）是 flange 接入的第二块高通板，但它与 Q6A 是**另一种高通形态**，更贴近 flange 原生的 **U-Boot 世界**：

- 启动链 PBL→XBL→TZ/HYP→**ABL→U-Boot→Linux**，U-Boot 以 Android boot image 被 ABL 链加载，经 `sysboot`（即 **extlinux**）引导内核——这正是 flange 现有 RK/AW 平台复用的 `builder/extlinux.py` 模型。
- bootloader（XBL/ABL/TZ/HYP + U-Boot boot.img）与 OS（boot/rootfs）**挤在同一块 eMMC** 的固定 vendor GPT（约 67 分区）里，没有 Q6A 那样的独立 SPI NOR——因此 flange **不能**像 Q6A 那样 `write-sector 0` 整盘重建 GPT（会抹掉 vendor bootloader 分区），只能按分区把 `boot`/`rootfs` 写进既有槽位。
- 刷写用 **qdl**（Debian/Ubuntu apt 直装，官方 Arduino/Armbian/qcom-linux 一致工具）+ rawprogram/firehose，EDL 经 JCTL 跳线进入。
- 设备树 `qrb2210-arduino-imola.dts` 已进 **mainline Linux 7.0**；Wi-Fi 是 **ath10k**（mainline 驱动），GPU 是 **Adreno 702**（Mesa freedreno），外设成熟度优于 Q6A 的 AIC8800 OOT。

新增该平台既接入一块真实量产板，也为 flange 沉淀「高通 + U-Boot + extlinux + eMMC 固定 GPT + qdl 按分区刷」这一套与 Q6A 互补的高通形态。

上游路径已在调研阶段逐项实证（2026-06-21，GitHub / Armbian PR / Qualcomm 文档）：
- 内核：`qrb2210-arduino-imola.dts`（代号 Imola/UnoQ）已进 **mainline Linux 7.0**（dt-bindings + dts 均上游）；Armbian edge（PR #9710）已从 `arduino/linux-qcom` fork 切到 mainline `v7.0`，验证可用。
- 启动模型（Armbian PR #9623 实证）：ABL→U-Boot(Android boot.img)→`sysboot`/extlinux 从 eMMC GPT 分区读 kernel+initrd，定制 `boot-qrb2210.cmd` 规避 ABL 保留内存区的 load 地址。
- bootloader blob：`armbian/qcombin`「Agatti/arduino-uno-q」+ `armbian/firmware#123` 含 XBL/ABL/TZ/HYP/GPT/rawprogram/firehose loader + U-Boot boot.img，高通签名 blob，flange 复用、不编译。
- 刷写：`qdl --allow-missing --storage emmc prog_firehose_ddr.elf rawprogram[0-9].xml patch[0-9].xml`（linux-msm/qdl ≥2.1，apt 可装）；EDL VID:PID `05c6:9008`（与 Q6A 探测一致），JCTL 跳线进入。
- 外设：GPU Adreno 702（Mesa freedreno + 固件）、Wi-Fi ath10k（mainline + linux-firmware）、BT、DSP/modem 固件随 linux-firmware/dragonwing 固件包。

## What Changes

- **新增平台 `qualcommqrb2210`**（flange 第二个 Qualcomm 平台）：`components/platform/qualcommqrb2210/config.py`（PLATFORM）+ `qrb2210/config.py`（SOC），由 registry 自动发现。
- **新增平台构建规则** `builder/platforms/qualcommqrb2210/`：`kernel.py`（git 编 **mainline Linux v7.0** + arm64 `defconfig`（+ 按需 qcom fragment）+ `qrb2210-arduino-imola.dtb` + modules）、`boot.py`（**U-Boot extlinux/sysboot**：复用 `builder/extlinux.py`，生成 `extlinux.conf` + Image + dtb + initrd，按需平台 load 地址）、`bootloader.py`（取 Arduino/armbian 预编 EDL blob 包 + U-Boot Android boot.img，**不编译**）、`rootfs.py`（ubuntu-base noble + Mesa freedreno + linux-firmware(-dragonwing) + ath10k）、`image.py`（**按分区**：boot + rootfs，并生成 flange rawprogram；**不重建整盘 GPT**）、`recovery.py`（先 stub），并导出 `ARTIFACT_NAMES` / `create_builder`。
- **新增刷写策略** `QualcommQrb2210FlashStrategy`（`builder/flash.py`）：基于 **qdl / EDL 模式**；`qdl --allow-missing --storage emmc prog_firehose_ddr.elf rawprogram*.xml patch*.xml` **按分区**写 `boot`/`rootfs`（vendor 分区原样保留）；vendor bootloader blob 经 vendor rawprogram 单刷（bring-up 一次）；host 工具 `qdl`（apt 可装）。
- **新增板 `arduino-uno-q`**：`components/board/arduino-uno-q/config.py`，绑定 `soc=qrb2210`、`platform=qualcommqrb2210`、dtb `qrb2210-arduino-imola.dtb`。
- **分区模型**：尊重 vendor 固定 eMMC GPT，flange 仅声明并写入既有 `boot`（extlinux 内容）+ `rootfs`（ext4）两个槽位，**不重新分区**。
- **新增知识库条目** `wiki/boards/arduino-uno-q.md` + `wiki/platforms/qualcommqrb2210-平台.md`（项目惯例）。

## Capabilities

### New Capabilities

- `qualcommqrb2210-platform`：Qualcomm QRB2210 平台/SoC 构建契约——内核源（**mainline Linux v7.0** + arm64 `defconfig` + `qrb2210-arduino-imola.dtb` + drm/msm/ath10k）、boot 形态（**U-Boot extlinux/sysboot**，复用 `builder/extlinux.py`，console `ttyMSM0`）、bootloader（消费 Arduino/armbian 预编 EDL blob + U-Boot Android boot.img、不编译）、rootfs（ubuntu-base noble + Mesa freedreno/turnip + Adreno 702 固件 + ath10k 固件 + linux-firmware）、image（**按分区** boot+rootfs，不重建整盘 GPT）、以及 `ARTIFACT_NAMES`/`create_builder` 契约。
- `qualcommqrb2210-flash`：Qualcomm qdl 刷写契约——`QualcommQrb2210FlashStrategy` 经 `qdl` 在 EDL 模式下 `--storage emmc` + rawprogram/patch **按分区**写 `boot`/`rootfs`（`--allow-missing` 跳过 vendor 槽），vendor bootloader blob 经 vendor rawprogram 单刷（bring-up）；设备探测（9008）、EDL（JCTL 跳线）诊断、qdl host 工具定位。
- `qualcommqrb2210-arduino-uno-q`：Arduino UNO Q 板级配置契约——`soc=qrb2210`、`platform=qualcommqrb2210`、dtb `qrb2210-arduino-imola.dtb`；板级不覆盖 SoC 层 kernel/boot/image 字段的约束。

### Modified Capabilities

（无 — 本变更为纯增量新增平台/SoC/板/刷写。不修改现有 spec 的 requirement；新平台经 registry 自动发现机制接入，无需改动 registry/engine，亦不改动 `qualcommqcs6490` 的任何契约。）

## Impact

- **代码层**：新增 `builder/platforms/qualcommqrb2210/`（6 个规则文件 + `__init__.py`）；`builder/flash.py` 新增 `QualcommQrb2210FlashStrategy`（不改现有策略，含 Q6A 的 `QualcommFlashStrategy`）。
- **内容层**：新增 `components/platform/qualcommqrb2210/{config.py,qrb2210/config.py}` + `components/board/arduino-uno-q/config.py`（+ rawprogram 模板/firmware 按需）。
- **host 工具**：新增依赖 `qdl`（apt `sudo apt install qdl`，≥2.1），EDL 模式经 JCTL 跳线进入。
- **外部依赖**（已实证）：mainline `linux` `v7.0`（内核 + dtb），Arduino/armbian EDL blob 包（XBL/ABL/TZ/HYP/GPT/rawprogram/firehose + U-Boot boot.img），ubuntu noble Mesa，linux-firmware(-dragonwing)（Adreno 702 + ath10k）。
- **目标硬件**：eMMC 存储（512 字节扇区），固定 vendor GPT（约 67 分区）。
- **lunch target**：`arduino-uno-q-*` 由现有 product/variant 机制生成。

## 非目标

- **不编译 boot 固件**：XBL / ABL / TZ / HYP / U-Boot boot.img 等是高通签名 / 平台 blob，flange 首发只消费 Arduino/armbian 预编包，不从源构建（U-Boot 自编留作后续增量）。
- **不重建整盘 GPT**：UNO Q 的 bootloader 与 OS 共享同一块 eMMC 的固定 vendor GPT，flange 只按分区写 `boot`/`rootfs`，不 `write-sector 0` 重分区（区别于 Q6A 独立 UFS 的整盘模型）。
- **不做 GRUB/UEFI 路线**：boot loader 走 U-Boot extlinux（复用 flange 原生 extlinux 模型），不在本板实现 GRUB/systemd-boot。
- **不做 AIC8800**：Wi-Fi 走 mainline ath10k，不复用 Q6A 的 AIC8800 USB OOT。
- **不做 arduino/linux-qcom fork 首发**：内核选定 mainline `v7.0`（dts 已上游）；Arduino fork 仅作 fallback，不在本变更范围。
- **不承诺自编 U-Boot**：v1 复用预编 U-Boot Android boot.img；从源编 U-Boot + mkbootimg 留作后续。
- **不改动现有平台与引擎**：不动 `builder/platforms/{rockchip,allwinnera733,amlogic,qualcommqcs6490}`、不改 registry/engine 的发现逻辑。
