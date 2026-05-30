## Context

flange 当前 qcs6490 基线（[qcs6490/config.py](../../../components/platform/qualcommqcs6490/qcs6490/config.py)）：
- 内核 `radxa/kernel.git@kernel.qclinux.1.0.r1-rel`（6.6.90 vendor BSP），`qcom_defconfig`，dtb `qcs6490-radxa-dragon-q6a`，`disable_configs=[MODULE_SIG_FORCE]`，`jobs=2`（arm64 Mac 跑 amd64 QEMU，大 vendor 模块易 OOM）。
- 启动：SPI(XBL→EDK2 UEFI) → GPT(4K) → ESP(GRUB) → grub-with-dtb → kernel+dtb → rootfs；刷写走 EDL/edl-ng。

Path A（`enable-q6a-venus-codec`）已实板证伪：BSP 的 `qcm6490-addons.dtsi` 删了 venus iommus 适配 downstream 驱动，mainline venus 不可用（dma_set_mask -EIO；补 iommus → SoC 复位）。详见 [[project_q6a_venus_codec_deadend]]。

Recon 已确认：
- `radxa/kernel.git` 的 **`linux-6.18.2` 分支存在**，最新 commit 为 `ufs: qcom: add PA_TACTIVATE quirk`（分支自带 UFS qcom 修复——这正是当初 6.18.2 撞 UFS 复位所缺的）。
- Armbian qcs6490 family 用的就是这个分支（`type: mainline`），patch 目录仅一个 `patching_config.yaml`、无内联 patch → **分支自带 q6a bring-up + 修复，几乎无需额外 patch**。
- Armbian 启动模型 `grub-with-dtb`、`SERIALCON=ttyMSM0`，与 flange 一致。

## Goals / Non-Goals

**Goals:**
- 用最小改动（换分支为主）让 qcs6490 跑在 mainline `linux-6.18.2` 上。
- 首个里程碑：`default` 能启动 + UFS 稳定 + 硬件 codec（`/dev/video*` + v4l2 枚举）。
- 复用现有 grub-with-dtb 的 boot/image/EDL 流水线，不重写构建引擎。
- 把已死的 Path A 干净作废、移除有害 patch。

**Non-Goals:**
- 不一次性重验全部 BSP 功能（屏/wifi/adb/GPU 逐项推进）。
- 不切 `edge`(7.0)；不照搬 Armbian defconfig/DTS/patch 全套。
- 不动 SPI 上的 XBL/EDK2 预编 blob。

## Decisions

### 决策 1：只换分支，复用 flange 现有流水线（不照搬 Armbian 框架）
- **选择**：`repos.kernel.branch` 改 `linux-6.18.2`，仍用 flange 的 kernel.py/boot/image/rootfs 流水线与 grub-with-dtb。
- **理由**：用户选定"只换内核分支"；Armbian 与 flange 启动模型一致，分支自带 bring-up，改动面最小、可回退（改回 branch 即恢复 BSP）。
- **备选**：整体对齐 Armbian build 框架。已否（用户决策 + 改动过大）。

### 决策 2：先 recon 再切，分阶段验证（先 default 启动/UFS，后 codec，再逐项功能）
- **选择**：实施顺序 = recon 分支事实 → 切分支构建出 dtb/Image → 静态核对（venus DT 带 iommus、dtb 名、defconfig）→ 刷机验证 default 启动 + UFS → 验证 codec → 再逐项重验屏/wifi/adb/GPU。
- **理由**：mainline 迁移 blast radius 大；分阶段把"能启动 + UFS 不复位"这个高风险门槛前置，避免一次性大改难以定位。
- **回退**：任意阶段卡死，`branch` 改回 `kernel.qclinux.1.0.r1-rel` 重建即恢复已知可用 BSP。

### 决策 3：defconfig 策略待 recon 定（mainline 可能无 `qcom_defconfig` 同名/同内容）
- **选择**：recon 确认 `linux-6.18.2` 是否仍提供 `qcom_defconfig` 及其是否 builtin-heavy（UFS/PHY/RPMh =y）；若差异大，参考 Armbian 对该分支的 config 片段对齐 venus(`VIDEO_QCOM_VENUS`/`IRIS`)、UFS、drm/msm。
- **理由**：mainline defconfig 与 vendor 可能不同；codec 与 UFS 的 config 必须确认开启。

### 决策 4：作废 Path A 并移除有害 patch（在本变更内完成清理）
- **选择**：删除 `0002-dts-sc7280-enable-venus-video-codec.patch`；归档/取消 `enable-q6a-venus-codec` 变更。
- **理由**：该 patch 仅对 BSP 有意义且已证伪；mainline 分支 venus 自带 iommus，无需它。

## Risks / Trade-offs

- [mainline 6.18.2 上 BSP 功能集体回退] → 屏/wifi/adb/GPU 暂不可用。缓解：分阶段，先保 default+UFS+codec；其余作为后续任务；BSP 分支随时可回退兜底。
- [meizu panel/aic8800 OOT 驱动在 6.18.2 编不过/绑定变化] → 重验阻塞。缓解：作为独立后续任务，KBUILD/DT 绑定按 6.18 API 适配；不阻塞 codec 里程碑。
- [defconfig 差异导致 UFS/codec/网络未开启或 builtin 缺失] → 启动/功能失败。缓解：recon 对齐 config；参考 Armbian 对该分支的配置。
- [board 的 PIL-firmware-paths patch / dwc3 patch 在 6.18.2 上下文漂移] → 构建中断。缓解：recon 复核两个保留 patch 是否仍 apply；漂移则重做或删除（mainline 可能已不需要）。
- [dtb 名 / DT 节点路径变化致 grub.cfg、fdtoverlay、adb 验证脚本失配] → 启动或验证脚本失效。缓解：recon 核对 mainline dtb 名与 soc 节点路径（如 `/proc/device-tree/soc@0/...`）。
- [构建资源] → mainline 大编译在 arm64 Mac/amd64 QEMU 上耗时/OOM。缓解：沿用 `jobs=2`，必要时清旧产物（[[project_bsp_volume_full]]）。

## Migration Plan

1. Recon：核对 `linux-6.18.2` 的 qcs6490 venus DT（iommus 在否）、dtb 名、defconfig 名/内容、两个保留 patch 是否适用。
2. 切分支 + 调 config，`flange build kernel` 出 Image/dtb；静态核对 venus okay+iommus、dtb 名。
3. EDL 刷整镜像，验证 default 启动 + UFS 稳定（串口 ttyMSM0 看启动）。
4. 验证 codec：venus probe 成功、`/dev/video*`、`v4l2-ctl` 枚举。
5. 逐项重验：屏 / aic8800 wifi / adb 自愈 / GPU drm/msm（各自独立任务）。
6. 清理：移除 patch 0002，作废 Path A change，更新 wiki。
7. **回退**：任意步骤失败 → `branch` 改回 BSP 重建。

## Open Questions

- `linux-6.18.2` 是否提供与 flange 兼容的 defconfig（`qcom_defconfig`?），venus/IRIS/UFS/drm-msm 是否默认开启？（recon task 1）
- mainline dtb 名是否仍为 `qcs6490-radxa-dragon-q6a`？soc 节点路径是否变化（影响验证脚本）？
- board `0001-dts-...-PIL-firmware-paths.patch` 在 mainline 是否仍需要（mainline 可能已用正确 firmware-name 或 split 格式）？
- Armbian 是否对该分支额外注入 DTS/overlay（patching_config 的 `dts-directories: source dt` 指向何处）？需进一步确认。
