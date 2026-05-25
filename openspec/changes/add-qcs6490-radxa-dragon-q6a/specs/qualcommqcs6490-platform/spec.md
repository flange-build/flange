## ADDED Requirements

### Requirement: 平台与 SoC 自动发现

`components/platform/qualcommqcs6490/config.py` MUST 导出 `PLATFORM` 变量，`components/platform/qualcommqcs6490/qcs6490/config.py` MUST 导出 `SOC` 变量，使 `builder/config/registry.py` 的自动发现机制无需任何硬编码即可识别该平台与 SoC。

#### Scenario: 平台被自动发现

- **WHEN** `_load_platform_config("qualcommqcs6490")` 被调用
- **THEN** 成功返回平台配置字典，不抛 `ValueError`

#### Scenario: SoC 被自动发现

- **WHEN** `_load_soc_config("qcs6490")` 被调用
- **THEN** 成功返回 SoC 配置字典，其所属平台为 `qualcommqcs6490`

### Requirement: 内核从 radxa/kernel git 构建

`builder/platforms/qualcommqcs6490/kernel.py` MUST 从 `radxa/kernel.git` 的 `linux-6.18.2` 分支克隆内核源，使用 `qcom_module_defconfig`（含 `qcom_module.config` 片段）构建，产出内核 `Image`、设备树 `qcs6490-radxa-dragon-q6a.dtb` 及模块，且配置 MUST 启用 `CONFIG_DRM_MSM`（开源 Adreno 内核驱动）。

#### Scenario: 内核源与分支正确

- **WHEN** 解析 `qcs6490` SoC 配置的内核 repo 字段
- **THEN** repo 指向 `radxa/kernel.git`，branch 为 `linux-6.18.2`

#### Scenario: 产出 dtb 与模块

- **WHEN** 执行内核构建
- **THEN** 产物包含 `qcs6490-radxa-dragon-q6a.dtb`、内核 `Image` 与内核模块

### Requirement: GRUB UEFI 启动（grub-with-dtb）

`builder/platforms/qualcommqcs6490/boot.py` MUST 以 **GRUB** 作为 UEFI 引导器：在 ESP 安装 GRUB EFI，经 GRUB `devicetree` 指令加载单个 dtb，内核命令行 MUST 含 `acpi=off`（强制走 DeviceTree）与 console `ttyMSM0`。MUST NOT 使用 extlinux 或 U-Boot。

#### Scenario: grub.cfg 含 devicetree 指令

- **WHEN** 生成 GRUB 配置
- **THEN** grub.cfg 含 `devicetree` 指令指向 `qcs6490-radxa-dragon-q6a.dtb`

#### Scenario: 内核命令行强制 DT 与串口

- **WHEN** 生成内核命令行
- **THEN** 包含 `acpi=off` 与 `console=ttyMSM0`

### Requirement: bootloader 消费 Radxa 预编 EDK2 固件

`builder/platforms/qualcommqcs6490/bootloader.py` MUST 取用 Radxa 预编的 EDK2 SPI 固件包（含 `xbl.elf`、`PILFv`、`prog_firehose_ddr.elf`、`rawprogram0.xml`、`patch0.xml` 等），不得从源码编译任何高通签名固件（XBL/TZ/EDK2）。

#### Scenario: 不编译签名固件

- **WHEN** 执行 bootloader 步骤
- **THEN** 仅暂存/校验 Radxa 预编固件 blob，无任何 XBL/EDK2 编译动作

### Requirement: rootfs 启用开源 Adreno 与板载外设

`builder/platforms/qualcommqcs6490/rootfs.py` MUST 基于 ubuntu-base `noble` 构建，并安装：开源 Mesa（freedreno/turnip）用户态、Adreno GPU 固件 `a660_zap.mbn` 与 `a660_sqe.fw`、AIC8800 USB Wi-Fi 固件（复用 a7a 配置）、以及 Qualcomm 远程处理器/音频固件与 alsa-ucm 配置。

#### Scenario: 安装开源 GPU 栈

- **WHEN** 构建 rootfs
- **THEN** 安装 Mesa freedreno/turnip 用户态与 `a660_zap.mbn`/`a660_sqe.fw` 固件，不安装高通闭源 GL blob

#### Scenario: 基底为 noble

- **WHEN** 解析 rootfs 配置
- **THEN** ubuntu-base 套件为 `noble`

### Requirement: GPT 镜像 ESP+rootfs 与 UFS 4K 扇区

`builder/platforms/qualcommqcs6490/image.py` MUST 产出 GPT 分区镜像，仅含 **ESP（FAT，label `efi`，含 GRUB EFI + 内核 + dtb + initrd）** 与 **rootfs（ext4，label `rootfs`）** 两个分区，不含 Radxa rsdk 的 p1 "config" 分区；面向 UFS 时 MUST 按 4096 字节扇区对齐。

#### Scenario: 仅两分区

- **WHEN** 生成镜像分区表
- **THEN** 仅有 ESP（FAT）与 rootfs（ext4）两个分区，无 config 分区

#### Scenario: UFS 4K 扇区

- **WHEN** 为 UFS 目标生成镜像
- **THEN** GPT 与分区按 4096 字节扇区对齐
