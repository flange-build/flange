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

rootfs MUST 基于 Ubuntu 24.04 noble，并 MUST 安装 Armbian SC8280XP 路线要求的 `bluez`、`protection-domain-mapper`、`qrtr-tools`、Mesa、`linux-firmware` 等用户态包。系统 MUST 从固定的 `radxa-pkg/radxa-firmware` commit 安装 Q8B ADSP、CDSP、SLPI、QUP、display 与 VPU 固件，MUST 以 SHA-256 校验安装 Radxa ALSA UCM backport deb，并 MUST 从 flange hardware package 安装 Q8B 专用 AudioReach topology 与 FastRPC runtime。

#### Scenario: 固件路径匹配 DTS

- **WHEN** 构建 Q8B rootfs
- **THEN** DTS 引用的 `qcom/sc8280xp/radxa/dragon-q8b/qcadsp8280.mbn`、`qcom/sc8280xp/qupv3fw.elf`、`qcom/sc8280xp/LENOVO/21BX/qcdxkmsuc8280.mbn` 与 `qcom/vpu/vpu20_p4_gen2_s6.mbn` 均被安装

#### Scenario: 第三方 deb 可验证

- **WHEN** 下载 Radxa ALSA UCM backport
- **THEN** 构建器在安装前校验配置声明的 SHA-256，校验失败则中止

#### Scenario: Q8B AudioReach topology 路径匹配内核请求

- **WHEN** 构建 Q8B rootfs
- **THEN** flange 将 `components/packages/firmware-qcom-audioreach` 的本地 vendor component 重新打成自有 deb，并由 rootfs 安装 `qcom/sc8280xp/SC8280XP-Radxa-Dragon-Q8B-tplg.bin`，且不直接安装上游 deb

#### Scenario: FastRPC 不依赖 Radxa 发行版 deb

- **WHEN** 构建 Q8B rootfs
- **THEN** flange 从 `components/packages/radxa-q8b-fastrpc` 生成并安装
  `fastrpc`、`libadsp-default-listener1`、`libadsprpc1`、
  `libcdsp-default-listener1` 与 `libcdsprpc1`
- **AND** flange 从独立的 `components/packages/radxa-firmware-sc8280xp`
  `vendor` component 生成并安装官方同名 `radxa-firmware-sc8280xp` deb
- **AND** 各 library deb 只携带对应 SONAME library，`fastrpc` 只携带 Q8B
  ADSP/CDSP daemon、udev/systemd 配置，DSP runtime 与 `/usr/lib/dsp` 路由由
  `radxa-firmware-sc8280xp` 携带
- **AND** 构建过程不下载或安装 `fastrpc` / `libcdsprpc1` / `radxa-firmware-sc8280xp` 上游 deb
- **AND** release 不包含 `fastrpc-test`，debug 包含该包及 v68 验证工具并可执行 `fastrpc_test -a v68`

#### Scenario: FastRPC deb 生命周期脚本经过 Q8B 适配

- **WHEN** flange 构建 `fastrpc` 与 ADSP/CDSP library deb
- **THEN** `fastrpc/app.yaml` 将 App 内的 `postinst`、`prerm` 与 `postrm` 映射进 `control.tar.gz`
- **AND** 各 library `app.yaml` 将 `ldconfig` trigger 映射进各自的 `control.tar.gz`
- **AND** 脚本只管理 Q8B 的 ADSP/CDSP daemon，并在运行中的 systemd 环境执行 reload/启停
- **AND** 脚本不引用 SDSP、GDSP、CDSP1 或 `deb-systemd-helper`

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
