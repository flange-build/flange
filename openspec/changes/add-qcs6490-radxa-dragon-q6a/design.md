## Context

flange 现有三个平台（rockchip/allwinnera733/amlogic）均为 U-Boot 世界：U-Boot 从源编、extlinux 引导、平台私有刷写工具（rkdeveloptool/xfel）。Qualcomm QCS6490（Radxa Dragon Q6A）是完全不同的 UEFI/EDL 世界。

调研阶段（2026-05-25）已逐项实证（GitHub raw / 本地固件包 / Radxa rsdk 与 Armbian 配置）：
- Radxa rsdk `socs.json`：family=qualcomm，partition=gpt，firmware_type=**edk2**，suite=noble。
- 本地 `dragon-q6a_flat_build_wp_260120.zip`：SPI NOR 含 XBL/TZ/HYP/AOP/CPUCP/DEVCFG + **PILFv(EDK2 UEFI)** + VarStore + `prog_firehose_ddr.elf` + `rawprogram0.xml`/`patch0.xml`，4K 扇区。
- Armbian `radxa-dragon-q6a.conf` / `qcs6490.conf`：BOOTCONFIG=none（无 U-Boot），**GRUB + `grub-with-dtb` + `acpi=off`**，单 dtb 经 `devicetree`，console `ttyMSM0`，kernel=`radxa/kernel.git@linux-6.18.2`，GPU 固件 `a660_zap.mbn`/`a660_sqe.fw`，Wi-Fi=AIC8800 USB。
- `radxa/kernel@linux-6.18.2`：含 `qcs6490-radxa-dragon-q6a.dts` + `qcom_module_defconfig`，HEAD 为 UFS qcom quirk。

约束：高通启动固件（XBL/EDK2）是签名 blob，flange 不编；boot 固件存 SPI NOR、出厂预装；系统盘 UFS（4K 扇区）。

## Goals / Non-Goals

**Goals:**

- 新增 flange 首个 Qualcomm 平台 `qualcommqcs6490`，经 registry 自动发现接入，零改引擎。
- 内核从 `radxa/kernel@linux-6.18.2` git 编（含 dtb + drm/msm）。
- GRUB(grub-with-dtb) UEFI 启动，开源 Mesa(freedreno/turnip) GPU。
- edl-ng/EDL 刷写：系统盘 write-sector 到 UFS；SPI EDK2 固件 rawprogram 单刷。
- 接入 `radxa-dragon-q6a` 板，UFS 首发。

**Non-Goals:**

- 不编译 XBL/EDK2/TZ 等签名固件（消费 Radxa 预编包）。
- 不做 systemd-boot / ACPI / 运行时 DT overlay / Yocto / mainline 官方内核。
- v1 不承诺 eMMC/SD/NVMe；不改现有平台与 registry/engine 发现逻辑。

## Decisions

### 决策 1：GRUB(grub-with-dtb)，非 systemd-boot/extlinux

UEFI 世界两个候选：GRUB 与 systemd-boot。选 **GRUB + `grub-with-dtb` + `acpi=off`**。
- 理由：与 flange 的 ubuntu-base(noble) 最契合——内核 deb 的 postinst hook 自动管 dtb 与 grub.cfg；Armbian 在本板已用 GRUB 实证；内核可留 rootfs，ESP 小。
- 备选 systemd-boot（Radxa rsdk 用）：更极简但要自管内核→ESP 同步、ESP 要大、与 Ubuntu 默认 GRUB 工具链拧。放弃。
- extlinux 是 U-Boot 机制，本板无 U-Boot，不适用。

### 决策 2：内核 git 编 `radxa/kernel@linux-6.18.2`，非 mainline

- 理由：该分支已含 Q6A dts + `qcom_module_defconfig`（drm/msm/venus/UFS 等齐），HEAD 为 UFS qcom quirk，是 Armbian current 验证过的组合，bring-up 风险最低。
- 备选 mainline/torvalds（6.18+ 已含 dts）：更"官方"但外设使能成熟度参差，留作后续 edge。

### 决策 3：boot 固件消费 Radxa 预编 EDK2 blob，不编

- XBL/EDK2/TZ 为高通签名 blob；flange `bootloader.py` 仅暂存/校验 Radxa `flat_build` 包，经 edl-ng 刷 SPI（bring-up 一次）。

### 决策 4：GPU 走开源 Mesa freedreno/turnip + 固件 blob

- Adreno 643(a6xx) 由 Mesa freedreno(GL)/turnip(Vulkan) + 内核 drm/msm 支持，配固件 `a660_zap.mbn`/`a660_sqe.fw`（linux-firmware，可再分发）。零高通闭源 GL blob。

### 决策 5：刷写经 edl-ng/EDL，系统盘 write-sector 整盘

- 系统盘：`edl-ng --memory UFS write-sector 0 raw.img`（契合 flange raw.img 模型，免 rawprogram XML）。
- SPI 固件：`edl-ng --loader prog_firehose_ddr.elf --memory spinor rawprogram rawprogram0.xml patch0.xml`。
- EDL 模式手动进入（按钮 + USB3），detect_device 给诊断。

### 决策 6：分区简化为 ESP + rootfs，去掉 p1 config

- rsdk 通用 p1 "config" FAT 分区（板级配置）对 flange 非必须，去除以简化 image.py。GPT = ESP(FAT,"efi") + rootfs(ext4,"rootfs")。UFS 4K 扇区对齐。

### 决策 7：DT overlay 仅构建期预合并

- UEFI/GRUB 不支持运行时 overlay（Armbian 实证单 dtb）。v1 单 mainline dtb；需变体时构建期 `fdtoverlay` 合出 per-variant dtb，不做运行时叠加。

## Risks / Trade-offs

- **[edl-ng 行为/参数与文档有偏差]** → 以本地 `flat_build` 的 rawprogram0.xml + Radxa 文档为准；先用 SPI 固件单刷验证 edl-ng 通路，再刷系统盘。
- **[GRUB grub-with-dtb 在该 EDK2 下的 dtb 注入]** → 镜像构建后用 grub.cfg 含 `devicetree` 的 sanity check（Armbian 同款）；实板首验启动。
- **[radxa/kernel@6.18.2 defconfig 外设缺项]** → 落地第一步 dump `qcom_module_defconfig` 核 drm/msm/venus/UFS/usb/pcie/ath 是否齐；缺则补 config 片段。
- **[Mesa noble 版本对 a6xx 支持]** → 若 noble mesa 偏旧，turnip/freedreno 表现不足，备用 PPA/编新 mesa。
- **[UFS 4K 扇区 GPT 对齐]** → image.py 显式按 4096 扇区生成 GPT；与 512 介质区分。
- **[EDL 手动进入]** → 不可自动化，部署文档/诊断明确步骤。

## Migration Plan

1. 平台/SoC config + registry 自动发现打通（`flange lunch radxa-dragon-q6a-*` 可选中）。
2. kernel.py：git 编 `radxa/kernel@6.18.2` + `qcom_module_defconfig` → Image + dtb + modules（核 defconfig 外设）。
3. rootfs.py：ubuntu-base noble + mesa + GPU/Wi-Fi/DSP 固件 + alsa-ucm。
4. boot.py + image.py：GRUB(grub-with-dtb) ESP + GPT(ESP+rootfs) 4K → raw.img。
5. flash.py：QualcommFlashStrategy（edl-ng）；先 SPI 固件单刷验证 edl-ng，再 write-sector 系统盘。
6. 实板：EDL 刷 UFS → GRUB → 内核起 → console ttyMSM0 → 进 rootfs → 验 GPU(freedreno)/Wi-Fi。

回滚：纯增量平台/板；删除新增目录即恢复，不影响现有平台。

## Open Questions

- `qcom_module_defconfig` 外设清单是否需补片段（落地第一步核）。
- noble 自带 mesa 对 Adreno 643 是否够新（可能需 PPA/编新 mesa）。
- edl-ng host 工具的打包/调用方式（随仓 vendor 还是用户自备）。
- recovery.py 是否需要实质实现（v1 可 stub）。
