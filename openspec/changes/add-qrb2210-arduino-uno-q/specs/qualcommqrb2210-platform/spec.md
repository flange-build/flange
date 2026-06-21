## ADDED Requirements

### Requirement: 平台与 SoC 自动发现

`components/platform/qualcommqrb2210/config.py` MUST 导出 `PLATFORM` 变量，`components/platform/qualcommqrb2210/qrb2210/config.py` MUST 导出 `SOC` 变量，使 `builder/config/registry.py` 的自动发现机制无需任何硬编码即可识别该平台与 SoC，且 MUST NOT 改动既有 `qualcommqcs6490` 平台的任何配置。

#### Scenario: 平台被自动发现

- **WHEN** `_load_platform_config("qualcommqrb2210")` 被调用
- **THEN** 成功返回平台配置字典，不抛 `ValueError`

#### Scenario: SoC 被自动发现

- **WHEN** `_load_soc_config("qrb2210")` 被调用
- **THEN** 成功返回 SoC 配置字典，其所属平台为 `qualcommqrb2210`

### Requirement: 内核从 mainline Linux git 构建

`builder/platforms/qualcommqrb2210/kernel.py` MUST 从 mainline `linux` 仓库的 `v7.0` 标签克隆内核源，使用 arm64 `defconfig`（按需附加 flange qcom 配置片段）构建，产出内核 `Image`、设备树 `qrb2210-arduino-imola.dtb` 及模块，且配置 MUST 启用 `CONFIG_DRM_MSM`（开源 Adreno 内核驱动）与 `CONFIG_ATH10K`（Wi-Fi）。

#### Scenario: 内核源与版本正确

- **WHEN** 解析 `qrb2210` SoC 配置的内核 repo 字段
- **THEN** repo 指向 mainline `linux`，版本为 `v7.0`（非 arduino/linux-qcom fork）

#### Scenario: 产出 dtb 与模块

- **WHEN** 执行内核构建
- **THEN** 产物包含 `qrb2210-arduino-imola.dtb`、内核 `Image` 与内核模块

### Requirement: U-Boot extlinux 启动

`builder/platforms/qualcommqrb2210/boot.py` MUST 以 **U-Boot extlinux/sysboot** 作为引导方式，复用 `builder/extlinux.py` 生成 `extlinux/extlinux.conf`，并将内核 `Image`、`qrb2210-arduino-imola.dtb` 与 initrd 放入 `boot` 分区内容；内核命令行 MUST 含 console `ttyMSM0`。MUST NOT 使用 GRUB、systemd-boot 或 UEFI 启动路径。

#### Scenario: 生成 extlinux 配置

- **WHEN** 生成 boot 配置
- **THEN** 产出 `extlinux/extlinux.conf`，其 `FDT` 指向 `qrb2210-arduino-imola.dtb`，`LINUX` 指向内核 `Image`

#### Scenario: 内核命令行含串口

- **WHEN** 生成内核命令行
- **THEN** 包含 `console=ttyMSM0`

### Requirement: bootloader 消费预编 EDL 固件（含 U-Boot boot.img）

`builder/platforms/qualcommqrb2210/bootloader.py` MUST 取用 Arduino/armbian 预编的 EDL 固件包（含 `xbl`/`abl`/`tz`/`hyp`、U-Boot Android `boot.img`、firehose loader `prog_firehose_ddr.elf`、vendor `rawprogram*.xml`/`patch*.xml`、GPT 等），不得从源码编译任何高通签名固件（XBL/ABL/TZ/HYP），亦不从源编译 U-Boot。

#### Scenario: 不编译签名固件与 U-Boot

- **WHEN** 执行 bootloader 步骤
- **THEN** 仅下载/暂存/校验预编固件 blob 与 U-Boot boot.img，无任何 XBL/ABL/TZ/U-Boot 编译动作

### Requirement: rootfs 启用开源 Adreno 与 mainline ath10k

`builder/platforms/qualcommqrb2210/rootfs.py` MUST 基于 ubuntu-base `noble` 构建，并安装：开源 Mesa（freedreno/turnip）用户态、Adreno 702 GPU 固件、mainline `ath10k` Wi-Fi 固件（经 `linux-firmware`/`linux-firmware-dragonwing`），以及 Qualcomm 远程处理器/音频固件。

#### Scenario: 安装开源 GPU 栈

- **WHEN** 构建 rootfs
- **THEN** 安装 Mesa freedreno/turnip 用户态与 Adreno 702 固件，不安装高通闭源 GL blob

#### Scenario: Wi-Fi 走 ath10k

- **WHEN** 解析 rootfs 的 Wi-Fi 固件配置
- **THEN** 安装 mainline `ath10k` 固件，不使用 AIC8800 OOT 模块

#### Scenario: 基底为 noble

- **WHEN** 解析 rootfs 配置
- **THEN** ubuntu-base 套件为 `noble`

### Requirement: 按分区镜像，不重建整盘 GPT

`builder/platforms/qualcommqrb2210/image.py` MUST 按分区产出 `boot`（含 extlinux 内容：`extlinux.conf` + Image + dtb + initrd）与 `rootfs`（ext4）两个分区镜像，并生成仅含这两个条目的 flange rawprogram 片段（指向 vendor 固定 GPT 的既有 `boot`/`rootfs` 槽位）。MUST NOT 组装整盘 raw 镜像、MUST NOT 重写或重建 vendor GPT 分区表。eMMC 目标按 512 字节扇区对齐。

#### Scenario: 仅产 boot 与 rootfs 分区镜像

- **WHEN** 生成镜像
- **THEN** 产物为 `boot` 分区镜像与 `rootfs` 分区镜像，无 monolithic 整盘 raw.img，无新建 GPT

#### Scenario: flange rawprogram 仅含两条目

- **WHEN** 生成 flange rawprogram 片段
- **THEN** 仅含 `boot` 与 `rootfs` 两个 FILE 条目，其余 vendor 分区不在其中
