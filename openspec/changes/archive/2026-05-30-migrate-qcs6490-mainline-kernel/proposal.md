## Why

Radxa Dragon Q6A (QCS6490) 当前用 radxa/kernel 的 vendor BSP 分支 `kernel.qclinux.1.0.r1-rel`（6.6.90）。该 BSP 为适配高通 downstream 视频驱动，在 `qcm6490-addons.dtsi` 主动删除了 venus 的 `iommus` 与 decoder/encoder 子节点——导致 mainline `qcom-venus` 路线彻底不可用：实板验证下，仅改 `status` 会因 venus 未挂 SMMU → 受限 `dma_mask` 被 direct-DMA 拒绝 → probe `-EIO`；补回 iommus 让 probe 走深则直接触发 **SoC 复位**（详见 [[project_q6a_venus_codec_deadend]]）。

Armbian 的 qcs6490 family 用的是**同一个 `radxa/kernel.git` 仓库的 mainline 分支 `linux-6.18.2`**（`type: mainline`，社区维护），启动模型同为 `grub-with-dtb`，且 codec（含 VP9）+ UFS 均经生产验证。该分支已自带 q6a bring-up 与 UFS qcom 修复（最新 commit 为 UFS PA_TACTIVATE quirk）。切到此基线即可获得**开箱可用的硬件视频编解码**，并对齐一个可持续的 mainline 基线。

## What Changes

- 将 qcs6490 SoC 的内核源分支从 `kernel.qclinux.1.0.r1-rel` 切换为 **`linux-6.18.2`**（仓库 `radxa/kernel.git` 不变）。
- 按 mainline 6.18 调整内核配置（defconfig 选择、dtb 名核对、`disable_configs` 复核），复用现有 `grub-with-dtb` 的 boot/image/EDL 刷写流水线。
- 作废 Path A 变更 `enable-q6a-venus-codec`，**移除已证实有害的平台 patch** `0002-dts-sc7280-enable-venus-video-codec.patch`。
- 目标里程碑：`radxa-dragon-q6a-default-*` 在 mainline 上能启动、UFS 稳定、`/dev/video*` 出现且 `v4l2-ctl` 枚举编解码能力。
- BSP 上已验证的功能在新内核上**逐项重新验证/适配**（不在本变更一次性全包）：魅族 E3 屏 OOT 三件套（panel_meizu_e3 / sec_ts / sgm37604a）、aic8800 wifi、adb 自愈、GPU drm/msm。

## Capabilities

### New Capabilities
- `qcs6490-mainline-kernel`: qcs6490 基于 mainline `linux-6.18.2` 的内核基线（分支来源、构建产物、default 启动 + UFS 稳定 + 硬件 codec 可用、既有功能的重验门槛）。

### Modified Capabilities
<!-- 无现有 spec 的需求级行为变化；codec 能力由本基线提供，Path A 的 q6a-venus-codec 随其变更作废 -->

## Impact

- **SoC 配置**：`components/platform/qualcommqcs6490/qcs6490/config.py` 的 `repos.kernel.branch` 改为 `linux-6.18.2`；`defconfig` / `dtb` / `disable_configs` 按 mainline 复核。
- **平台 patch**：移除 `components/platform/qualcommqcs6490/patches/kernel/0002-dts-sc7280-enable-venus-video-codec.patch`（BSP 专用、已死）；复核 `0001-dwc3-...` 与 board 的 `0001-dts-...-PIL-firmware-paths.patch` 是否仍适用于 6.18.2。
- **构建系统**：kernel.py 的 `-@`/dtb 合并逻辑、boot/image/rootfs 流水线预期可复用（grub-with-dtb 不变），但需复核 mainline 内核的模块/固件布局差异。
- **OOT 驱动 / 固件**：meizu-e3-panel 三件套与 aic8800 需在 6.18.2 上重新编译验证（KBUILD API、符号、DT 绑定可能变化）。
- **首个里程碑只保证 default 启动 + UFS + codec**；屏/wifi/adb/GPU 重验作为后续任务，期间这些功能可能暂时回退。
- **变更管理**：作废 `openspec/changes/enable-q6a-venus-codec`（Path A）。

## 非目标

- 不在本变更内一次性恢复并验证所有 BSP 功能（屏/wifi/adb/GPU 逐项重验，单独推进）。
- 不实现上层视频应用（GStreamer/播放器/转码），仅交付硬件 codec 的底层可用 + 验证。
- 不切换到 Armbian 的 `edge`（7.0）分支；本变更锁定 `current` 对应的 `linux-6.18.2`。
- 不照搬 Armbian 的 defconfig/DTS/patch 全套体系（用户选定"只换内核分支"，最小改动复用现有 flange 流水线）。
- 不改动 SPI 上的 XBL/EDK2 UEFI 预编 blob（仍由 Radxa 提供）。
