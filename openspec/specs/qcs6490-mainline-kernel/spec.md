# qcs6490-mainline-kernel Specification

## Purpose
定义 qcs6490 SoC 在 mainline `radxa/kernel@linux-6.18.2` 基线上的能力契约：内核基线切换、default 产物启动与 UFS 稳定、硬件视频编解码（venus），以及在该基线上重新验证通过的板载外设默认能力（AIC8800 USB Wi-Fi、adb-over-USB gadget）。
## Requirements
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

### Requirement: 既有功能重验门槛

迁移 SHALL 以"default 启动 + UFS + codec"为首个完成里程碑；BSP 上已验证的功能（魅族 E3 屏、aic8800 wifi、adb 自愈、GPU drm/msm）SHALL 作为后续独立任务在新内核上逐项重新验证，并 SHALL 在文档中记录各项重验状态。

#### Scenario: 里程碑达成判定
- **WHEN** default 启动 + UFS 稳定 + codec 三项均实板通过
- **THEN** 首个里程碑视为达成；屏/wifi/adb/GPU 的重验状态在 wiki 中逐项标注（通过 / 待办 / 回退）

#### Scenario: 任意阶段可回退到 BSP
- **WHEN** 迁移过程中某阶段在 mainline 上无法通过
- **THEN** 将 `repos.kernel.branch` 改回 `kernel.qclinux.1.0.r1-rel` 重建即可恢复已知可用的 BSP 基线

### Requirement: AIC8800 USB Wi-Fi 默认可用

mainline 6.18.2 不带 in-tree aic8800 驱动，系统 SHALL 以 out-of-tree 模块从 `radxa-pkg/aic8800` 编译 `aic_load_fw` 与 `aic8800_fdrv` 并随 rootfs 安装，使板载 AIC8800 D80 USB Wi-Fi 作为 qcs6490 平台默认能力开机即可用。OOT 编译 SHALL 适配该内核版本的 cfg80211 API（`get_tx_power` 新增 `radio_idx`/`link_id` 参数），并 SHALL 串行编译（`MAKEFLAGS= make -j1`）以规避大文件交叉编译在受限容器内的 OOM。固件 SHALL 安装到驱动查找路径 `/lib/firmware/aic8800D80/`。

#### Scenario: 驱动加载且射频工作
- **WHEN** default 产物开机
- **THEN** `lsmod` 含 `aic8800_fdrv`/`aic_load_fw`、出现 `wlx<MAC>` 无线接口，`iw dev <iface> scan` 能扫到周边 AP

### Requirement: 魅族 E3 屏（meizu-e3-bringup product）在 mainline 重验通过

`radxa-dragon-q6a-meizu-e3-bringup-*` 产物 SHALL 在 mainline 6.18.2 基线上完成魅族 E3 39pin MIPI-DSI 屏的显示 + 触摸 + 背光 bring-up：经 `meizu-e3-panel` 包注入的 `panel_meizu_e3`/`sec_ts`/`sgm37604a` 三个 OOT 驱动 SHALL 能对 mainline 6.18 内核编译通过（适配 `asm/fb.h`/`asm/unaligned.h` 移除、`GPIOF_DIR_IN`→`GPIOF_IN`、`FB_EVENT_BLANK` 移除等 ABI 漂移，并 SHALL 同时保持 rock5b/a7a 旧 BSP 内核可编）。触摸/背光所在 `i2c13` SHALL 去除 base board dts 的 `qcom,enable-gsi-dma`（`patches/kernel/0003`），使 geni i2c 走 FIFO 模式、避免 GPI DMA 传输失败；该改动 SHALL NOT 影响 default 产物。

#### Scenario: 显示 + 触摸 + 背光实板可用
- **WHEN** 刷入 meizu-e3-bringup 产物并上电、屏接到 J10 LCD FPC
- **THEN** `/sys/class/drm/card0-DSI-1` 为 `connected`/`enabled` @ 1080×2160 且面板有画面、`sec_ts` 读到 device id `AC,6F,70` 且手指触摸使其 IRQ(gpio81) 计数累增、`/sys/class/backlight/sgm37604a` 亮度可写且生效

#### Scenario: i2c13 无 GPI DMA 传输失败
- **WHEN** meizu-e3-bringup 产物开机、`sec_ts`/`sgm37604a` 在 `i2c13` 上 probe
- **THEN** `dmesg` 无 `geni_i2c ... GPI transfer failed`，触摸与背光的 i2c 读写均成功

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

> 注：硬件**编码**亦可用，但**前提是系统以 EL2 启动**（UEFI `Hypervisor Settings → Hypervisor Override` 开启、Gunyah hypervisor 激活、`/dev/kvm` 出现）：此时 mainline venus `/dev/video1` 端到端硬件编码 H.264/HEVC 通过、零复位（`v4l2h264enc` 720p NV12→6.46MB 有效 H264）。EL1（默认）下喂帧即整机复位——真根因是 hypervisor 介导编码器的 CP/secure 内存，**与驱动(venus/iris)/固件/发行版无关**（此前"固件/TZ 死路"结论已据此修正）。flange 默认 EL2（UEFI 变量持久化或定制 flat_build）为待解项。详见记忆 `qcs6490-venus-encode-soc-reset`。

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

