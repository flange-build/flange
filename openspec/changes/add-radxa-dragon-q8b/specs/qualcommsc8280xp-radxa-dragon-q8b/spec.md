## ADDED Requirements

### Requirement: SC8280XP 平台与 SoC 自动发现

系统 MUST 提供 `qualcommsc8280xp` 平台配置和 `sc8280xp` SoC 配置，并 MUST 通过现有 registry 自动发现机制加载；平台构建入口 MUST 复用现有 Qualcomm UEFI/GRUB 构建器，不复制其实现。

#### Scenario: 平台与 SoC 被发现

- **WHEN** 加载 `qualcommsc8280xp` 平台和 `sc8280xp` SoC
- **THEN** 两者均返回配置字典，且 SoC 的 `platform` 等于 `qualcommsc8280xp`

#### Scenario: 构建器复用

- **WHEN** 新平台为 kernel、bootloader、rootfs、boot、recovery 或 image 创建构建器
- **THEN** 返回现有 Qualcomm 对应构建器，且不维护第二份实现

### Requirement: Radxa 7.0.11 内核与 Q8B Device Tree

SC8280XP 配置 MUST 将 kernel repo 锁定到 `radxa/kernel` 的 `linux-7.0.11` 已知 commit，MUST 使用 `radxa_qcom_7_0_defconfig`，并 MUST 构建 `Image`、modules 与 `qcom/sc8280xp-radxa-dragon-q8b.dtb`。UFS、QMP PHY 和 SC8280XP interconnect MUST 为 built-in；drm/msm MUST 作为模块在 rootfs 可用后加载。

#### Scenario: 内核输入可复现

- **WHEN** 解析 `sc8280xp` SoC 配置
- **THEN** kernel repo、branch、commit、defconfig 与 dtb 均为固定值

#### Scenario: 无 initramfs 的 UFS 启动依赖

- **WHEN** 合并内核配置覆盖
- **THEN** UFS、QMP PHY 与 SC8280XP interconnect 保持 built-in，且 `CONFIG_DRM_MSM=m`

### Requirement: Q8B rootfs 固件与用户态

rootfs MUST 基于 Ubuntu 24.04 noble，并 MUST 安装 Armbian SC8280XP 路线要求的 `bluez`、`protection-domain-mapper`、`qrtr-tools`、Mesa、`linux-firmware` 等用户态包。系统 MUST 从固定的 `radxa-pkg/radxa-firmware` commit 安装 Q8B ADSP、CDSP、SLPI、QUP、display 与 VPU 固件，并 MUST 以 SHA-256 校验安装 Radxa ALSA UCM backport deb。

#### Scenario: 固件路径匹配 DTS

- **WHEN** 构建 Q8B rootfs
- **THEN** DTS 引用的 `qcom/sc8280xp/radxa/dragon-q8b/qcadsp8280.mbn`、`qcom/sc8280xp/qupv3fw.elf`、`qcom/sc8280xp/LENOVO/21BX/qcdxkmsuc8280.mbn` 与 `qcom/vpu/vpu20_p4_gen2_s6.mbn` 均被安装

#### Scenario: 第三方 deb 可验证

- **WHEN** 下载 Radxa ALSA UCM backport
- **THEN** 构建器在安装前校验配置声明的 SHA-256，校验失败则中止

### Requirement: UEFI、GRUB 与 4K UFS 镜像

系统 MUST 使用 Radxa Q8B 预编 SPI UEFI flat_build 固件，MUST 生成含 GRUB EFI 的 ESP 和 ext4 rootfs 两个 GPT 分区，并 MUST 按 4096 字节逻辑扇区生成 UFS raw 镜像。GRUB MUST 加载 Q8B DTB，内核命令行 MUST 含 `acpi=off`、`console=ttyMSM0` 与 `root=PARTLABEL=rootfs`。

#### Scenario: Q8B GRUB 配置

- **WHEN** 生成 Q8B boot.img
- **THEN** grub.cfg 的菜单标题为 Radxa Dragon Q8B，并加载 `sc8280xp-radxa-dragon-q8b.dtb`

#### Scenario: UFS 镜像布局

- **WHEN** 生成 Q8B raw.img
- **THEN** 镜像的 sector size 为 4096，且分区仅为 ESP 与 rootfs

### Requirement: Qualcomm EDL 刷写路由

`qualcommsc8280xp` 平台 MUST 复用 `QualcommFlashStrategy`，通过 Q8B flat_build 中的 `prog_firehose_ddr.elf` 执行 `edl-ng --memory UFS write-sector 0` 整盘刷写，并保留 SPI `rawprogram0.xml`/`patch0.xml` 恢复路径。

#### Scenario: 新平台选择 EDL 策略

- **WHEN** flash 配置平台为 `qualcommsc8280xp`
- **THEN** `get_flash_strategy` 返回 `QualcommFlashStrategy`

### Requirement: Q8B board 与 lunch target

`components/board/radxa-dragon-q8b/config.py` MUST 导出 `BOARD`，声明 `board=radxa-dragon-q8b`、`soc=sc8280xp`、`platform=qualcommsc8280xp`，并 MUST 通过现有 product/variant 机制生成 debug 与 release target。

#### Scenario: 解析 Q8B debug target

- **WHEN** 解析 `radxa-dragon-q8b-default-debug`
- **THEN** FINAL_CONFIG 包含正确的 board、soc、platform、product、variant 与 Q8B DTB

#### Scenario: 枚举 Q8B targets

- **WHEN** 枚举有效 lunch targets
- **THEN** 同时包含 `radxa-dragon-q8b-default-debug` 与 `radxa-dragon-q8b-default-release`
