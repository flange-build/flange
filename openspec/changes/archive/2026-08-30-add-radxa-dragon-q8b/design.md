## Context

Dragon Q8B 使用 Qualcomm SC8280XP，启动链为 SPI 中的签名 XBL/EDK2 UEFI → GRUB → Linux，系统盘可为 4096 字节逻辑扇区的 UFS。flange 已为 Dragon Q6A 实现 Qualcomm UEFI/GRUB、GPT 镜像和 EDL 刷写流水线，但平台名和部分显示文本带有 QCS6490 假设。

本变更以 `/Volumes/bsp/armbian/config/boards/radxa-dragon-q8b.conf`、`config/sources/families/sc8280xp.conf` 和 Radxa 官方资源为输入。Armbian 的稳定路线使用 `radxa/kernel` 的 `linux-7.0.11`、`sc8280xp-radxa-dragon-q8b.dtb`、板级固件及 GRUB `grub-with-dtb`。

## Goals / Non-Goals

**Goals:**

- 生成 `radxa-dragon-q8b-default-{debug,release}` lunch target。
- 构建 Radxa 7.0.11 内核、板级 DTB、模块、Ubuntu rootfs、GRUB ESP 和 4K UFS raw 镜像。
- 安装 Q8B 启动及主要外设所需的 SC8280XP 固件和 Radxa ALSA UCM 配置。
- 复用现有 Qualcomm 构建/刷写实现，仅消除阻碍第二块 Qualcomm SoC 接入的写死值。

**Non-Goals:**

- 不重构既有 Qualcomm 平台命名或类名。
- 不从源码构建 Qualcomm 签名启动固件。
- 不在本变更实现 ACPI、recovery、运行时 DT overlay、蓝牙地址生成或 Armbian 的可选 HDMI 热插拔补丁集。
- 不以未具备硬件的 CI 代替实板外设验证。

## Decisions

### 决策 1：增加薄平台入口，直接复用现有 Qualcomm 构建器

新增 `qualcommsc8280xp` 平台配置和同名 builder 入口；入口只转发到已存在的 Qualcomm kernel/bootloader/rootfs/boot/image/recovery 构建器，并复用 `QualcommFlashStrategy`。这避免复制六个实现文件，也避免为一次板卡接入重命名 `qualcommqcs6490`。

备选方案是把现有平台整体重构为通用 `qualcomm`；该方案会扩大迁移面并影响已验证的 Q6A，不采用。

### 决策 2：使用 Radxa `linux-7.0.11` 与其完整 defconfig

内核锁定 `radxa/kernel` 分支 `linux-7.0.11` 的具体 commit，使用仓库内 `radxa_qcom_7_0_defconfig`。该 defconfig 已启用 SC8280XP、UFS、QMP PHY、SC8280XP interconnect、drm/msm 与音频等选项，且分支内已包含 Q8B DTS。

为避免无 initramfs 的 flange 启动链在挂载 rootfs 前请求显示固件，板级配置将 `CONFIG_DRM_MSM` 覆盖为模块；UFS、PHY 与 interconnect 保持 built-in。现有 Qualcomm kernel builder 改用共享的 inline config 解析器，使这项覆盖不需要新 fragment 文件。

Armbian `sc8280xp-vendor` 的 HDMI 热插拔增强属于体验修复而非基础启动前提，本变更不复制约一千行补丁；实板确认需要时再单独提案。

### 决策 3：声明式安装锁定的板级固件、AudioReach topology 与 UCM 包

复用 `rootfs.extra_firmware` 从 `radxa-pkg/radxa-firmware` 的固定 commit 安装 ADSP、CDSP、SLPI、QUP、display 和 VPU 固件。display 固件同时按 DTS 要求落到 Lenovo 兼容路径。复用 `rootfs.extra_debs` 安装 Armbian 使用的 Radxa `alsa-ucm-conf` backport，并固定 SHA-256。

Q8B 专用 AudioReach topology 由 `components/packages/firmware-qcom-audioreach`
硬件特性包携带，从 Radxa `1.0.4-2` deb 中只提取板级 topology 数据，并通过
package `vendor` component 注册为本地 custom package。flange 使用
AppBuilder / DebBuilder 将其重新打成自有 deb，再通过 rootfs 的统一 `dpkg`
流程安装；构建过程不安装上游 deb，也不继承其发行版依赖或 maintainer script。

FastRPC 由 `components/packages/radxa-q8b-fastrpc` 提供。参考 Radxa `fastrpc
1.0.7-1` 与 `radxa-firmware-sc8280xp 0.2.41` deb 后，按官方包边界生成
`fastrpc`、`libadsp-default-listener1`、`libadsprpc1`、
`libcdsp-default-listener1`、`libcdsprpc1` 与 debug-only `fastrpc-test`。每个
library deb 只携带对应 SONAME library；`fastrpc` 只携带 Q8B 实际使用的
ADSP/CDSP daemon、udev/systemd 配置，并增加 `sysusers.d` 与 Q8B 固定
`soc_id=498` 初始化。SDSP/GDSP/CDSP1 与 v75 test 不进入 Q8B 包。

上游 maintainer script 不原样继承：`fastrpc` vendor App 通过
`maintainer_scripts` 映射 Q8B 专用 `postinst` / `prerm` / `postrm`，各 library
deb 独立映射 `ldconfig` trigger；脚本只管理 ADSP/CDSP，不依赖
`deb-systemd-helper`。来自 Radxa firmware deb 的 Q8B ADSP/CDSP DSP runtime
与 `/usr/lib/dsp` 路由由独立的
`components/packages/radxa-firmware-sc8280xp` hardware package 提供；该
package 使用 `vendor` component，并生成官方同名 `radxa-firmware-sc8280xp`
deb。大型 remoteproc/display/VPU 固件仍由已锁定的外部来源安装。

启动所需的 remoteproc/display/VPU 等较大固件继续使用锁定的外部来源；FastRPC
执行期必须使用的 Q8B DSP runtime 随 package 携带，避免构建期依赖 Radxa APT
源或从上游 deb 动态提取。

### 决策 4：沿用 ESP + rootfs 的 4K UFS 镜像与 EDL 路线

Q8B 与 Q6A 共享 UEFI/GRUB 和 UFS 形态，因此沿用 GPT 两分区、`sector_size=4096`、`root=PARTLABEL=rootfs` 及 `edl-ng write-sector`。bootloader 组件只下载 Radxa Q8B 预编 flat_build 包，供 EDL firehose 与 SPI 恢复使用。

### 决策 5：共享 GRUB 菜单标题从 board 配置派生

现有 boot builder 将菜单标题写死为 Dragon Q6A。改为把 `config["board"]` 的连字符替换为空格并 title-case，不新增配置字段；Q6A 的标题保持等价，Q8B 自动得到正确标题。

## Risks / Trade-offs

- **[Radxa 分支或固件上游变化]** → kernel 与 firmware 均锁定 commit，升级另行验证。
- **[Q8B flat_build 包布局变化]** → 沿用 firehose loader 搜索逻辑，并以 URL/loader 字段做配置测试。
- **[模块化 drm/msm 与实板自动加载不一致]** → 配置解析测试确认覆盖生效；实板首验检查 `/dev/dri` 与固件加载日志。
- **[基础支持缺少 Armbian HDMI 热插拔增强]** → 保留为明确非目标；只有实板复现 KVM/replug 问题时才引入对应补丁。
- **[EDL 整盘写 UFS 未在 CI 执行]** → CI 只验证命令路由和配置，实际写盘必须在 Q8B 上确认。
- **[FastRPC DSP runtime 增加约 30 MiB 仓库内容]** → 独立放入
  `radxa-firmware-sc8280xp` hardware package，仅保留 Q8B 的 ADSP/CDSP 目录
  并记录参考 deb SHA-256；不携带其他 SoC、SDSP/GDSP、dbgsym 或 v75 test。

## Migration Plan

1. 新增平台、SoC、board 配置及薄 builder 入口。
2. 泛化共享 GRUB 标题与 kernel inline config 解析。
3. 注册 Qualcomm EDL 策略别名并增加配置测试。
4. 依次验证配置解析、目标枚举、Python 测试、内核配置/DTB 构建；具备硬件时再验证 UFS 启动与外设。

回滚时删除新增平台/board/OpenSpec 文件，并还原共享 builder 的两处泛化与 flash 策略别名即可；Q6A 配置和产物格式不变。

## Open Questions

- Q8B 实板是否需要把 Armbian 的 HDMI bridge/replug 补丁纳入默认内核。
- 蓝牙卡实际型号及无公开地址时是否需要复用 Armbian 的 machine-id 地址生成服务。
