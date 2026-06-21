## Context

flange 已有四个 U-Boot 世界平台（rockchip/allwinnera733/amlogic 均 U-Boot+extlinux）与一个 UEFI 世界平台（qualcommqcs6490 = GRUB/EDK2/edl-ng 整盘）。Arduino UNO Q（Qualcomm QRB2210/QCM2290，代号 Imola/Agatti）是**第二块高通板，但落在 U-Boot extlinux 一侧**：高通签名启动链拉起 U-Boot，U-Boot 用 `sysboot`（extlinux）引导内核——可直接复用 flange 原生 `builder/extlinux.py`。

调研阶段（2026-06-21）已逐项实证（mainline / Armbian PR / armbian-qcombin / Qualcomm 文档）：
- **内核**：`qrb2210-arduino-imola.dts`（代号 Imola/UnoQ）+ dt-bindings 已进 **mainline Linux 7.0**；Armbian PR #9710 把 edge kernel 从 `arduino/linux-qcom@qcom-v7.0.0-unoq` 切到 mainline `v7.0`，实证可用。
- **启动链**（Armbian PR #9623）：PBL→XBL→TZ/HYP→**ABL→U-Boot(Android boot.img)→Linux**；U-Boot 经 `sysboot`/extlinux 从 eMMC GPT 分区读 kernel+initrd，定制 `boot-qrb2210.cmd` 规避 ABL 保留内存区的 load 地址。
- **存储/分区**：eMMC，512 字节扇区，**固定 vendor GPT 约 67 分区**（bootloader + OS 同盘）。
- **bootloader blob**：`armbian/qcombin`「Agatti/arduino-uno-q」+ `armbian/firmware#123` 含 XBL/ABL/TZ/HYP/GPT/rawprogram/firehose loader + U-Boot boot.img。
- **刷写**：`qdl --allow-missing --storage emmc prog_firehose_ddr.elf rawprogram[0-9].xml patch[0-9].xml`（linux-msm/qdl ≥2.1，Debian/Ubuntu apt 可装）；EDL 经 JCTL 跳线，VID:PID `05c6:9008`。
- **外设**：GPU Adreno 702（Mesa freedreno + 固件）、Wi-Fi **ath10k**（mainline）、BT、DSP/modem 固件随 linux-firmware/dragonwing。

约束：高通启动固件（XBL/ABL/TZ/HYP/U-Boot boot.img）是签名/平台 blob，flange 不编；bootloader 与 OS 共享同一块 eMMC 固定 vendor GPT，flange 只能按分区写 `boot`/`rootfs`。

## Goals / Non-Goals

**Goals:**

- 新增 flange 第二个 Qualcomm 平台 `qualcommqrb2210`，经 registry 自动发现接入，零改引擎。
- 内核从 **mainline Linux v7.0** git 编（含 `qrb2210-arduino-imola.dtb` + drm/msm/ath10k）。
- **U-Boot extlinux/sysboot** 启动（复用 `builder/extlinux.py`），开源 Mesa（freedreno）GPU、mainline ath10k Wi-Fi。
- **qdl 按分区刷**：`boot`/`rootfs` 写进固定 vendor GPT 既有槽位；vendor bootloader blob rawprogram 单刷（bring-up）。
- 接入 `arduino-uno-q` 板，eMMC 首发。

**Non-Goals:**

- 不编译 XBL/ABL/TZ/HYP 等签名固件，亦不从源编 U-Boot（首发消费预编 boot.img）。
- 不做 GRUB/UEFI/systemd-boot；不重建整盘 GPT；不做 AIC8800；不做 arduino fork 首发。
- 不改现有平台（含 Q6A）与 registry/engine 发现逻辑。

## Decisions

### 决策 1：boot 走 U-Boot extlinux/sysboot，复用 `builder/extlinux.py`

UNO Q 的 U-Boot 经 `sysboot`（即 extlinux）引导，与 flange 现有 RK/AW 平台一致。
- 理由：直接复用 `builder/extlinux.py` 生成 `extlinux/extlinux.conf` + Image + dtb + initrd，零新增 boot loader；Armbian 在本板已用 U-Boot+sysboot 实证。
- 备选 GRUB（Q6A 路线）：本板无 EDK2 UEFI 启动入口（ABL 直接拉 U-Boot），不适用。
- **wrinkle**：Armbian 用定制 `boot-qrb2210.cmd`（显式 load 地址规避 ABL 保留内存区）。若 stock extlinux 默认 load 地址与 ABL 保留区冲突，`boot.py` 需提供平台特定 load 地址 / boot 脚本。落地第一步以实板/Armbian 脚本核对。

### 决策 2：内核 git 编 mainline Linux v7.0，非 arduino fork

- 理由：`qrb2210-arduino-imola.dts` + dt-bindings 已上游进 mainline 7.0；Armbian edge 已切 mainline `v7.0` 验证；ath10k/Adreno/venus 全 mainline，避免 fork 维护。
- 备选 `arduino/linux-qcom@qcom-v7.0.0-unoq`：更贴近原厂初始使能，留作 fallback（外设若缺项时回退）。
- defconfig：用 arm64 `defconfig`（含 qcom），按需补 flange qcom fragment——落地第一步 dump 核对 `DRM_MSM`/`ATH10K`/venus/eMMC/usb/GENI 串口是否齐（沿用 Q6A 同款核对法）。

### 决策 3：bootloader 消费 Arduino/armbian 预编 EDL blob，不编（含 U-Boot boot.img）

- XBL/ABL/TZ/HYP 为高通签名 blob；U-Boot 虽可自编，但首发风险最低的做法是消费 `armbian/qcombin` 预编 U-Boot Android boot.img。
- `bootloader.py` 仅下载/暂存/校验 EDL blob 包（含 firehose loader `prog_firehose_ddr.elf` + vendor rawprogram/patch + U-Boot boot.img），经 qdl 单刷 vendor 槽（bring-up 一次）。
- U-Boot 自编 + mkbootimg（qcom-deb-images `build-u-boot-rb1.sh` 路径）留作后续增量。

### 决策 4：image 按分区（boot + rootfs），不重建整盘 GPT

- UNO Q 的 bootloader 与 OS **共享同一块 eMMC 固定 vendor GPT（约 67 分区）**；`write-sector 0` 整盘会抹掉 vendor bootloader 分区。
- 对比 Q6A：Q6A 的 bootloader 在**独立 SPI NOR**、OS 在**独立 UFS**，故能整盘 write-sector 重建 OS 盘 GPT。UNO Q 无此独立介质，**必须按分区**。
- `image.py` 不组装 monolithic raw.img、不写 GPT；产出 `boot/boot.img`（extlinux 内容的分区镜像）+ `rootfs/rootfs.img`，并生成 flange rawprogram 片段（仅 `boot`/`rootfs` 两个 FILE 条目，指向既有 vendor 分区 label/sector）。

### 决策 5：刷写经 qdl 按分区，非 edl-ng 整盘

- 系统：`qdl --allow-missing --storage emmc prog_firehose_ddr.elf <flange rawprogram>.xml <patch>.xml` —— `--allow-missing` 跳过未提供镜像的 vendor 槽，仅写 `boot`/`rootfs`。
- vendor bootloader：bring-up 一次性 `qdl ... <vendor rawprogram*.xml> <patch*.xml>` 刷 XBL/ABL/TZ/HYP/U-Boot/GPT。
- 工具选 **qdl**（apt 可装、Arduino/Armbian/qcom 官方一致）而非 Q6A 的 edl-ng（需手动下载）；新增独立 `QualcommQrb2210FlashStrategy`，不复用 Q6A 的 `QualcommFlashStrategy`（整盘 write-sector 语义不同）。
- EDL 经 **JCTL 跳线** 进入；`detect_device` 探测 9008（复用 Q6A 同款 USB 拓扑探测），未命中给 JCTL 诊断。

### 决策 6：分区模型尊重 vendor 固定 GPT

- flange 不重新分区。board/SoC config 的 `partitions` 仅声明 flange 写入的 `boot`（extlinux 内容）+ `rootfs`（ext4）两个既有槽位（label/sector 取自 vendor rawprogram），用于生成 flange rawprogram 片段。eMMC 512 字节扇区。

### 决策 7：GPU 开源 Mesa freedreno + Adreno 702 固件；Wi-Fi mainline ath10k

- Adreno 702 由 Mesa freedreno（GL）/turnip（Vulkan）+ 内核 drm/msm 支持，配固件（linux-firmware 的 a702 zap/sqe）。
- Wi-Fi 走 **mainline ath10k**（+ linux-firmware），省掉 Q6A 的 AIC8800 OOT 编译 + OOM 治理。

## Risks / Trade-offs

- **[U-Boot load 地址与 ABL 保留区冲突]** → 落地第一步比对 Armbian `boot-qrb2210.cmd` 的显式 load 地址；必要时 `boot.py` 提供平台特定 extlinux load 地址 / boot 脚本，而非纯 stock distro_bootcmd。实板首验。
- **[flange/vendor rawprogram 的 boot/rootfs label 与 sector]** → 以 `armbian/qcombin` 的 `rawprogram*.xml` 为权威，确认 flange 写入的 `boot`/`rootfs` 落哪个 partition label（Armbian 提到 partition 43）；flange rawprogram 仅改这两个 FILE 条目，其余继承 vendor。
- **[mainline v7.0 defconfig 外设缺项]** → 落地第一步 dump arm64 `defconfig` 核 `DRM_MSM`/`ATH10K`/venus/eMMC/GENI 串口/usb 是否齐；缺则补 flange qcom fragment 或回退 arduino fork。
- **[Adreno 702 固件是否在 linux-firmware]** → 核对 noble `linux-firmware` / `linux-firmware-dragonwing` 是否含 a702 zap/sqe；缺则单独取 Arduino 固件包。
- **[U-Boot boot.img 复用 vs 自编]** → 首发复用 armbian/qcombin 预编 boot.img；若其与 flange extlinux 约定（分区 label/load 地址）不匹配，再评估自编 + mkbootimg。
- **[EDL 经 JCTL 跳线]** → 不可自动化，部署文档 / detect_device 诊断明确步骤。
- **[blob 包 license / 重分发]** → 核对 armbian/qcombin 高通 blob 条款，决定 flange 直链下载还是要求用户自备。

## Migration Plan

1. 平台/SoC config + registry 自动发现打通（`flange lunch arduino-uno-q-*` 可选中）。
2. kernel.py：git 编 mainline `linux@v7.0` + arm64 `defconfig` → Image + `qrb2210-arduino-imola.dtb` + modules（核 defconfig 外设）。
3. rootfs.py：ubuntu-base noble + mesa freedreno + linux-firmware(-dragonwing)（Adreno 702 + ath10k）。
4. boot.py：复用 `builder/extlinux.py` 生成 extlinux.conf + Image + dtb + initrd（按需平台 load 地址）；image.py 按分区产 boot.img + rootfs.img + flange rawprogram。
5. bootloader.py：下载/暂存 armbian/qcombin EDL blob 包（含 U-Boot boot.img + firehose + vendor rawprogram）。
6. flash.py：`QualcommQrb2210FlashStrategy`（qdl）；先 vendor rawprogram 单刷 bootloader 验证 qdl 通路，再按分区刷 boot/rootfs。
7. 实板：JCTL 进 EDL → qdl 刷 vendor + boot/rootfs → ABL→U-Boot→extlinux→内核 → console ttyMSM0 → 进 rootfs → 验 GPU(freedreno)/Wi-Fi(ath10k)。

回滚：纯增量平台/板；删除新增目录即恢复，不影响现有平台（含 Q6A）。

## Open Questions

- flange 写入的 `boot`/`rootfs` 在 vendor GPT 的确切 partition label/sector（读 armbian/qcombin rawprogram 核对，Armbian 提到 partition 43）。
- U-Boot 是否必须定制 boot 脚本（ABL 保留内存区 load 地址），还是 stock extlinux 默认地址即可。
- mainline v7.0 arm64 `defconfig` 外设是否需补 flange qcom fragment（落地第一步核）。
- Adreno 702 固件是否在 noble linux-firmware（缺则单取 Arduino 固件包）。
- U-Boot boot.img 复用预编是否够用，还是需 flange 自编 + mkbootimg。
- recovery.py 是否需要实质实现（v1 可 stub）。
