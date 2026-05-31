## ADDED Requirements

### Requirement: 内核基线切换到 mainline linux-7.0.2

系统 SHALL 将 qcs6490 SoC 的内核源分支配置为 `radxa/kernel.git` 的 `linux-7.0.2`（mainline 7.0 系，Radxa linux-qcom 官方包同款分支），并 SHALL 复用现有 `grub-with-dtb` 的 boot/image/EDL 刷写流水线；构建出的内核 Image 与 dtb SHALL 来自该分支。

内核源 SHALL 在 `branch=linux-7.0.2` 基础上 pin `commit=7473a9fca2b08623319e497f4f811746baddb7bc`（= radxa linux-qcom 7.0.2-2 的 `src` 子模块），不跟随分支 tip（tip 已前移到会触发 UFS 复位的 commit）。

内核 config SHALL 对齐 radxa rsdk/linux-qcom 的**四段叠加**配方：`make defconfig qcom_module.config radxa.config radxa_custom.config`（顺序固定，后者覆盖前者）。其中 `qcom_module.config` 为内核 in-tree（软链 radxa `radxa_qcom_7_0_defconfig` 的 qcom 全量平台 config），`radxa.config` / `radxa_custom.config` 分别由 `0004` / `0005` patch 注入。flange 特定 `enable_configs`（`FW_LOADER_COMPRESS*`、USB gadget `configfs`/`F_FS`）SHALL 在四段后追加覆盖，`disable_configs` 仅保留 `MODULE_SIG_FORCE`。

#### Scenario: 内核从 linux-7.0.2 构建成功
- **WHEN** 配置 `repos.kernel.branch = linux-7.0.2` + `commit = 7473a9f` 并执行 `flange build kernel`
- **THEN** 成功检出该 commit 并编出 `Image` 与 `qcs6490-radxa-dragon-q6a` 对应的 dtb，无构建中断

#### Scenario: 四段 config 片段被正确合并
- **WHEN** 内核构建完成
- **THEN** 最终 `.config` 中 `qcom_module.config` 的 qcom 平台驱动均为 `=y`（如 `CONFIG_QCOM_AOSS_QMP`、`CONFIG_QCOM_LLCC`、`CONFIG_QCOM_QSEECOM`、`CONFIG_SCSI_UFS_QCOM`、`CONFIG_ARM_SMMU_V3`），radxa.config 典型项（`CONFIG_DMABUF_HEAPS=y` 等）与 radxa_custom.config 项（`CONFIG_MODULE_COMPRESS_ZSTD=y`、`CONFIG_EFI_ZBOOT` 未设）齐备

#### Scenario: kodiak.dtsi 基础上 patch 正确应用
- **WHEN** 内核构建时按序应用 0001–0005 patch（含同 commit 重建：`reset_source` 先 `git clean -fd` 清未跟踪残留）
- **THEN** `qcs6490-radxa-dragon-q6a.dts` 中 `usb_1` 的 `dr_mode` 为 `peripheral`、`i2c13` 不含 `qcom,enable-gsi-dma`，`radxa.config`/`radxa_custom.config` 被创建，全部 patch 无 `already exists` / 冲突报错

### Requirement: 硬件视频解码可用

系统 SHALL 在 linux-7.0.2 基线上使 venus 视频驱动 probe 成功并暴露 V4L2 节点，硬件解码 SHALL 端到端可用。

mainline `vpu20_p1.mbn`（约 2MB，来自 `linux-firmware`）SHALL 成功加载（远低于 DTS video_mem 5MB 与驱动 VENUS_FW_MEM_SIZE 6MB 限制）。

> 注：硬件**编码**经实板 venus + iris 两驱动验证均喂帧即整机复位（根在固件/TZ-CP 契约，驱动层无解），不在本基线能力范围；详见记忆 `qcs6490-venus-encode-soc-reset`。

#### Scenario: venus probe 成功且出现运行时节点
- **WHEN** 系统启动完成
- **THEN** `dmesg` 中 venus 驱动 probe 成功无 fatal 错误，`/dev/video*` 出现（`qcom-venus-decoder`/`-encoder`）

#### Scenario: 硬件解码端到端可用
- **WHEN** 对 8-bit 4:2:0 H.264 流执行 GStreamer `v4l2h264dec` 硬解管线
- **THEN** 管线跑完到 EOS（解出 NV12）、无报错、设备不复位

#### Scenario: venus 固件加载成功
- **WHEN** 系统启动，venus 驱动尝试加载 `qcom/vpu-2.0/venus.mbn`
- **THEN** `dmesg` 无固件加载失败（`-EINVAL` / size exceeded）日志，固件 probe 完成

### Requirement: ADB USB gadget 在 7.0.2 持续工作

DWC3 clear-stall patch SHALL 针对 linux-7.0.2 代码库重写，确保 macOS 主机发送 `ClearFeature(ENDPOINT_HALT)` 后 adbd 不退出。patch 逻辑（以 `DWC3_EP_DELAY_START` 替代取消 pending requests）不变，仅更新目标行号和 context。

#### Scenario: macOS 连接后 ADB 持续工作
- **WHEN** 将 Q6A 接入 macOS，macOS 完成 USB 配置并发送 ClearFeature
- **THEN** `adbd` 不退出，`adb devices` 持续显示设备，USB gadget 不注销重注册

### Requirement: QCS6490 专属固件通过 qcom-ppa 安装

rootfs SHALL 包含来自 `ubuntu-qcom-iot/qcom-ppa` 的 `linux-firmware-dragonwing` 包，该包将 QCS6490 ADSP/CDSP/GPU 固件更新置于 `/lib/firmware/updates/qcom/qcs6490/`，优先级高于 `linux-firmware` 提供的版本。

#### Scenario: rootfs 含 qcom-ppa 固件更新
- **WHEN** 构建 qcs6490 rootfs
- **THEN** rootfs 内 `/lib/firmware/updates/qcom/qcs6490/` 目录存在且含 `a660_zap.mbn`、`a660_gmu.bin` 等 GPU 固件

#### Scenario: GPU 固件从 updates/ 优先加载
- **WHEN** 系统启动，drm/msm 驱动加载 GPU 固件
- **THEN** `dmesg` 显示从 `/lib/firmware/updates/` 路径加载固件，无 firmware load 失败

## MODIFIED Requirements

### Requirement: default 产物启动与 UFS 稳定

系统 SHALL 保证 `radxa-dragon-q6a-default-*` 在 linux-7.0.2 基线上能正常启动到 rootfs，且 UFS 链路稳定、不发生 SoC 复位。

> 根因（实板）：UFS probe 早期 QHEE `PM: Reset by PSHOLD` 整机复位有**双根因**，二者都须修复：① 内核 config 漏 `qcom_module.config`（缺 `QCOM_AOSS_QMP`/`QCOM_LLCC`/`ARM_SMMU_V3`/`QCOM_IOMMU`/`QCOM_QSEECOM` 等 qcom 平台驱动）——由四段配方修复；② 板上 SPI EDK2/XBL 固件过旧（`251013`/00364-KODIAKLA）与 7.0.2 `kodiak` DTB 资源/握手不匹配——须刷新到 `260120`/00549-KODIAKWP。实板坐实 rootfs 挂载于 UFS `/dev/sda2`、零复位。

#### Scenario: default 启动到 rootfs
- **WHEN** 刷入 linux-7.0.2 基线镜像并上电
- **THEN** 串口（ttyMSM0）可见内核启动到 systemd、rootfs 挂载成功、adb/控制台可登录

#### Scenario: UFS 不复位
- **WHEN** 系统启动并访问 UFS 存储
- **THEN** 无 `ufs_qcom` probe 复位导致的 SoC reset，存储读写正常

#### Scenario: SPI 固件须与 7.0.2/kodiak DTB 匹配
- **WHEN** 迁移到 7.0.2（kodiak DTB）
- **THEN** SPI EDK2/XBL 固件 SHALL 刷新到配套版本（`260120`/00549-KODIAKWP 或更新，`flange flash --spi-firmware`）；停留旧版（`251013`/00364-KODIAKLA）会因资源/握手不匹配致 UFS probe QHEE PSHOLD 复位（`flange flash` 默认只刷 UFS、不动 SPI）

## REMOVED Requirements

### Requirement: 内核基线切换到 mainline linux-6.18.2
**Reason**: 内核基线升级至 linux-7.0.2，由新 requirement「内核基线切换到 mainline linux-7.0.2」替代（含 commit pin 与四段 config 配方）。

### Requirement: 硬件视频编解码可用
**Reason**: 7.0.2 实板验证硬件**编码**（venus + iris 两驱动）均喂帧即整机复位、不可用；能力收窄为新 requirement「硬件视频解码可用」。编码根因在固件/TZ-CP 契约，见记忆 `qcs6490-venus-encode-soc-reset`。

### Requirement: adb-over-USB gadget 默认可用
**Reason**: DWC3 clear-stall patch 针对 7.0.2 重写，由新 requirement「ADB USB gadget 在 7.0.2 持续工作」替代。
