## Why

flange 目前支持 Rockchip / Allwinner / Amlogic 三个平台，全部是 **U-Boot 世界**（U-Boot + extlinux + 平台私有刷写工具）。Qualcomm 一直是 ProjectSpec 列明的目标平台，但尚未实现——`platform-abstraction` spec 甚至把 `"qualcomm"` 当作"尚不支持的平台"反例。

Radxa Dragon Q6A（Qualcomm QCS6490 / Dragonwing）是 flange 接入 Qualcomm 的首块板。它与现有平台是**两个世界**：启动链 PBL→XBL→EDK2 UEFI→OS（非 U-Boot），刷写走 EDL 模式 + edl-ng（非 rkdeveloptool/xfel），boot 固件是 Radxa 预编签名 blob（flange 不编）。新增该平台既接入一块真实产品板，也为后续 Qualcomm 板（qcs9075 等）铺好平台地基，并兑现 platform 抽象层"为高通预留"的设计。

上游路径已在调研阶段逐项实证（2026-05-25，GitHub raw / 本地固件包）：
- 内核：`radxa/kernel.git` 分支 `linux-6.18.2` 存在，含 `arch/arm64/boot/dts/qcom/qcs6490-radxa-dragon-q6a.dts`，配 `qcom_module_defconfig` + `qcom_module.config`（drm/msm 等在内）；HEAD 含 UFS qcom quirk，针对本类板与目标 UFS 存储活跃维护中。
- boot 固件：本地 `dragon-q6a_flat_build_wp_260120.zip` 内含 `prog_firehose_ddr.elf`（firehose loader）、`xbl.elf`、`PILFv`(EDK2 UEFI)、`VarStore`、`rawprogram0.xml` + `patch0.xml`，SPI NOR 全套，4K 扇区。
- 启动模型：Radxa rsdk（products.json/socs.json）确认 family=qualcomm、partition=gpt、firmware_type=edk2、suite=noble；Armbian `radxa-dragon-q6a.conf`/`qcs6490.conf` 实证 GRUB（`grub-with-dtb` + `acpi=off`）、单 dtb 经 `devicetree`、console `ttyMSM0`、kernel=radxa/kernel@linux-6.18.2。
- GPU/外设：开源 Mesa freedreno/turnip（Adreno 643/a6xx）+ 固件 `a660_zap.mbn`/`a660_sqe.fw`；WiFi 为 AIC8800 USB 模组（与 a7a 同款，可复用）；DSP/音频 adsp/cdsp.mbn + tplg + radxa alsa-ucm-conf。

## What Changes

- **新增平台 `qualcommqcs6490`**（flange 首个 Qualcomm 平台）：`components/platform/qualcommqcs6490/config.py`（PLATFORM）+ `qcs6490/config.py`（SOC），由 registry 自动发现。
- **新增平台构建规则** `builder/platforms/qualcommqcs6490/`：`kernel.py`（git 编 `radxa/kernel@linux-6.18.2` + `qcom_module_defconfig` + dtb + modules）、`boot.py`（**GRUB + grub-with-dtb**：ESP 放 GRUB EFI，单 dtb 经 `devicetree`，`acpi=off ttyMSM0`）、`bootloader.py`（取 Radxa 预编 EDK2 SPI blob，**不编译**）、`rootfs.py`（ubuntu-base noble + Mesa freedreno + linux-firmware-qcom + AIC8800 + alsa-ucm）、`image.py`（GPT = ESP + rootfs，UFS 4K 扇区）、`recovery.py`（先 stub），并导出 `ARTIFACT_NAMES` / `create_builder`。
- **新增刷写策略** `QualcommFlashStrategy`（`builder/flash.py`）：基于 **edl-ng / EDL 模式**；`--memory UFS write-sector 0 raw.img` 刷系统盘；SPI EDK2 固件经 `--memory spinor rawprogram rawprogram0.xml patch0.xml` 单刷（bring-up）；host 工具 `edl-ng`（Radxa 提供）。
- **新增板 `radxa-dragon-q6a`**：`components/board/radxa-dragon-q6a/config.py`，绑定 `soc=qcs6490`、`platform=qualcommqcs6490`、dtb `qcs6490-radxa-dragon-q6a.dtb`，AIC8800 USB Wi-Fi 配置复用 a7a。
- **分区简化**：GPT 仅 **ESP(FAT,"efi") + rootfs(ext4,"rootfs")**，不带 Radxa rsdk 的 p1 "config" 分区。
- **DT overlay 策略**：v1 单 mainline dtb，无运行时 overlay（UEFI/GRUB 不具备）；如需变体（DSI 屏等）走**构建期 `fdtoverlay` 预合并**。
- **新增知识库条目** `wiki/boards/radxa-dragon-q6a.md` + `wiki/platforms/qualcommqcs6490.md`（项目惯例）。

## Capabilities

### New Capabilities

- `qualcommqcs6490-platform`：Qualcomm QCS6490 平台/SoC 构建契约——内核源（`radxa/kernel@linux-6.18.2` + `qcom_module_defconfig` + `qcs6490-radxa-dragon-q6a.dtb` + drm/msm）、boot 形态（GRUB `grub-with-dtb` + `acpi=off` + 单 dtb 经 `devicetree` + console `ttyMSM0`）、bootloader（消费 Radxa 预编 EDK2 SPI blob、不编译）、rootfs（ubuntu-base noble + Mesa freedreno/turnip + GPU 固件 `a660_zap.mbn`/`a660_sqe.fw` + AIC8800 + alsa-ucm）、image（GPT ESP+rootfs、UFS 4K 扇区）、以及 `ARTIFACT_NAMES`/`create_builder` 契约。
- `qualcommqcs6490-flash`：Qualcomm EDL 刷写契约——`QualcommFlashStrategy` 经 `edl-ng` 在 EDL 模式下 `write-sector` 刷系统盘到 UFS（`--memory UFS`），SPI EDK2 固件经 `rawprogram`/firehose（`prog_firehose_ddr.elf`）单刷；设备探测、pre_flash 配置生成、`--memory` 取值约束。
- `qualcommqcs6490-radxa-dragon-q6a`：Radxa Dragon Q6A 板级配置契约——`soc=qcs6490`、`platform=qualcommqcs6490`、dtb `qcs6490-radxa-dragon-q6a.dtb`、AIC8800 USB Wi-Fi 复用 a7a；板级不覆盖 SoC 层 kernel/boot/image 字段的约束。

### Modified Capabilities

（无 — 本变更为纯增量新增平台/SoC/板/刷写。不修改 `platform-abstraction` 等现有 spec 的 requirement；新平台经 registry 自动发现机制接入，无需改动 registry/engine。）

## Impact

- **代码层**：新增 `builder/platforms/qualcommqcs6490/`（6 个规则文件 + `__init__.py`）；`builder/flash.py` 新增 `QualcommFlashStrategy`（不改现有策略）。
- **内容层**：新增 `components/platform/qualcommqcs6490/{config.py,qcs6490/config.py}` + `components/board/radxa-dragon-q6a/config.py`（+ overlay/firmware 按需）。
- **host 工具**：新增 `edl-ng`（Radxa `edl-ng-dist.zip`），EDL 模式需手动进入（按钮 + USB3）。
- **外部依赖**（已实证）：`radxa/kernel.git@linux-6.18.2`（内核 + dtb + defconfig）、Radxa EDK2 SPI 固件包、ubuntu-qcom 相关固件/Mesa、AIC8800 固件（复用 a7a）。
- **目标硬件**：首发 UFS 存储（4K 扇区）；eMMC/SD/NVMe 后续。
- **lunch target**：`radxa-dragon-q6a-*` 由现有 product/variant 机制生成。

## 非目标

- **不编译 boot 固件**：XBL / EDK2 UEFI / TZ 等是高通签名 blob，flange 只消费 Radxa 预编包，不从源构建。
- **不做 ACPI 启动路线**：固定走 DT（`acpi=off`），不实现 ACPI 引导。
- **不做 systemd-boot**：boot loader 选定 GRUB（grub-with-dtb），不并行实现 systemd-boot。
- **不做运行时 DT overlay**：UEFI/GRUB 不支持；overlay 仅构建期预合并（v1 不实现，留接口）。
- **不做 mainline 官方内核 / Yocto 路线**：内核选定 `radxa/kernel@linux-6.18.2`；mainline、Yocto 不在本变更范围。
- **不承诺 eMMC/SD/NVMe 首发**：v1 仅 UFS 实证；其余介质后续增量。
- **不改动现有平台与引擎**：不动 `builder/platforms/{rockchip,allwinnera733,amlogic}`、不改 registry/engine 的发现逻辑（依赖既有自动发现）。
