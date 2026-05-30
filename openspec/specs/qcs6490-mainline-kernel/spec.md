# qcs6490-mainline-kernel Specification

## Purpose
TBD - created by archiving change migrate-qcs6490-mainline-kernel. Update Purpose after archive.
## Requirements
### Requirement: 内核基线切换到 mainline linux-6.18.2

系统 SHALL 将 qcs6490 SoC 的内核源分支配置为 `radxa/kernel.git` 的 `linux-6.18.2`（mainline 6.18 系），并 SHALL 复用现有 `grub-with-dtb` 的 boot/image/EDL 刷写流水线；构建出的内核 Image 与 dtb SHALL 来自该分支。MODULE_SIG_FORCE 等 flange 既有 `disable_configs` 约定 SHALL 在新基线上复核保持一致行为。

#### Scenario: 内核从 linux-6.18.2 构建成功
- **WHEN** 配置 `repos.kernel.branch = linux-6.18.2` 并执行 `flange build kernel`
- **THEN** 成功检出该分支并编出 `Image` 与 `qcs6490-radxa-dragon-q6a` 对应的 dtb，无构建中断

#### Scenario: venus DT 在 mainline 基线带 iommus
- **WHEN** 反查构建出的 dtb 中 `video-codec@aa00000`
- **THEN** 其 `status` 为 `okay` 且保留 `iommus`、`video-decoder`/`video-encoder` 子节点（不被 addons 类节点删除）

### Requirement: default 产物启动与 UFS 稳定

系统 SHALL 保证 `radxa-dragon-q6a-default-*` 在 mainline 基线上能正常启动到 rootfs，且 UFS 链路稳定、不发生 HS-G4 PHY 训练导致的 SoC 复位。

#### Scenario: default 启动到 rootfs
- **WHEN** 刷入 mainline 基线镜像并上电
- **THEN** 串口（ttyMSM0）可见内核启动到 systemd、rootfs 挂载成功、adb/控制台可登录

#### Scenario: UFS 不复位
- **WHEN** 系统启动并访问 UFS 存储
- **THEN** 无 `ufs_qcom` probe 复位 / HS-G4 PHY 训练失败导致的 SoC reset，存储读写正常

### Requirement: 硬件视频编解码可用

系统 SHALL 在 mainline 基线上使 venus 视频编解码 probe 成功并暴露 V4L2 运行时节点。

#### Scenario: venus probe 成功且出现运行时节点
- **WHEN** 系统启动完成
- **THEN** `dmesg` 中 venus 驱动 probe 成功无 fatal 错误，`/dev/video*` 与 `/dev/media*` 出现

#### Scenario: 可枚举编解码能力
- **WHEN** 执行 `v4l2-ctl --list-devices` 与对各节点 `v4l2-ctl -d <node> --all`
- **THEN** 列出解码器/编码器设备并可枚举受支持的 codec 像素格式

### Requirement: 既有功能重验门槛

迁移 SHALL 以"default 启动 + UFS + codec"为首个完成里程碑；BSP 上已验证的功能（魅族 E3 屏、aic8800 wifi、adb 自愈、GPU drm/msm）SHALL 作为后续独立任务在新内核上逐项重新验证，并 SHALL 在文档中记录各项重验状态。

#### Scenario: 里程碑达成判定
- **WHEN** default 启动 + UFS 稳定 + codec 三项均实板通过
- **THEN** 首个里程碑视为达成；屏/wifi/adb/GPU 的重验状态在 wiki 中逐项标注（通过 / 待办 / 回退）

#### Scenario: 任意阶段可回退到 BSP
- **WHEN** 迁移过程中某阶段在 mainline 上无法通过
- **THEN** 将 `repos.kernel.branch` 改回 `kernel.qclinux.1.0.r1-rel` 重建即可恢复已知可用的 BSP 基线

