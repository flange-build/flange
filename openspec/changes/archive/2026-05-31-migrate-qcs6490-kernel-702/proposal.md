## Why

flange qcs6490 此前使用 radxa/kernel@linux-6.18.2，该分支在硬件编解码（VPU）、内核稳定性上存在积累问题，且调试时遗留的非生产 patch 已混入构建缓存；Radxa 官方 linux-qcom 包已迁移至 linux-7.0.2 并在 qcs6490-noble-test 仓库验证，现在是将 flange 与上游对齐、全面激活 QCS6490 各硬件组件（GPU / VPU / WiFi / 触摸屏 / ADB）的合适时机。

## What Changes

- **内核分支 + commit 固定**：`linux-6.18.2` → `linux-7.0.2`（radxa/kernel.git），并在 `branch=linux-7.0.2` 基础上 pin `commit=7473a9fca2b08623319e497f4f811746baddb7bc`——即 radxa `linux-qcom` 7.0.2-2 的 `src` 子模块同款 commit。`linux-7.0.2` 分支 tip 已前移到 `6445af0c5`，该 tip 在本板 UFS probe 早期触发 QHEE PSHOLD 整机复位，故 pin 回已验证 commit。
- **内核 config 策略**：对齐 radxa rsdk/linux-qcom 的**四段叠加**配方 `defconfig qcom_module.config radxa.config radxa_custom.config`（见其 `.github/local/Makefile.local` 的 `KERNEL_DEFCONFIG`）。**关键是补回 `qcom_module.config`**——mainline `arch/arm64/configs/` 下软链到 radxa `radxa_qcom_7_0_defconfig` 的 qcom 全量平台 config，把 `QCOM_QSEECOM`/`QSEECOM_UEFISECAPP`、`QCOM_AOSS_QMP`、`QCOM_LLCC`、`ARM_SMMU_V3`、`QCOM_IOMMU`、`QCOM_PDC`/`MPM`、`RESET_QCOM_AOSS` 等数百项 qcom 平台驱动设 `=y`。漏掉它正是 UFS 复位根因。
- **enable_configs 收敛**：UFS/PHY/interconnect 已由 `qcom_module.config` 覆盖；`enable_configs` 仅作 flange 特定补充（`FW_LOADER_COMPRESS*` 加载 `.zst` 固件、`USB_LIBCOMPOSITE/CONFIGFS/F_FS` 供 adb gadget）。
- **disable_configs**：仅保留 `MODULE_SIG_FORCE`（OOT 模块不签名）。
- **DWC3 kernel patch 重写**：`0001-dwc3-gadget-clear-stall` 针对 7.0.2 行号重写，修复逻辑不变。
- **新增两个 config patch**：`0004-feat-radxa-common-kernel-config.patch`（radxa.config）+ `0005-feat-radxa-custom-kernel-config.patch`（radxa_custom.config，对齐 radxa debian `patches/series` 第二个 config 补丁；flange 在内核树根打补丁，路径去掉 radxa 的 `src/` 前缀）。`qcom_module.config` 为内核 in-tree，无需 patch。
- **构建器修复**：`Qcs6490KernelBuilder.reset_source` 覆盖加 `git clean -fd`——否则 commit 未变重建时，上次构建残留的未跟踪 `radxa.config`/`radxa_custom.config` 会让 new-file 补丁二次 `git apply` 报 `already exists` 失败。
- **SPI EDK2/XBL 固件刷新（迁移必需）**：旧固件（板上 `251013`/00364-KODIAKLA）与 7.0.2 `kodiak` DTB 的资源/握手不匹配，致 UFS probe 早期 QHEE `PM: Reset by PSHOLD` 整机复位；须 `flange flash --spi-firmware` 刷 `edk2_firmware_url` 指向的 `dragon-q6a_flat_build_wp_260120.zip`（00549-KODIAKWP）。⚠️ `flange flash` 默认只刷 UFS LUN0、**不碰 SPI**，迁移大版本内核/DTB 时极易漏掉固件更新。
- **rootfs 新增 `extra_apt_sources` 机制**：RootfsBuilder 基类新增能力，支持在 Phase 1 apt-get update 前写入外部 APT 源和 GPG key。
- **新增 ubuntu-qcom-iot/qcom-ppa 源**：为 QCS6490 添加 Qualcomm IoT PPA，安装 `linux-firmware-dragonwing`（提供 ADSP/CDSP/GPU 固件 updates/）。
- **Dockerfile 加 gnupg**：构建镜像补充 `gnupg`，支持 GPG key dearmor。

## Capabilities

### New Capabilities

- `qcs6490-extra-apt-sources`：rootfs 构建支持写入外部 APT 源（key + sources.list.d），供 Phase 1 apt-get 使用

### Modified Capabilities

- `qcs6490-mainline-kernel`：内核基线从 linux-6.18.2 升至 linux-7.0.2（pin commit 7473a9f）；config 策略对齐 radxa 四段叠加 `defconfig qcom_module.config radxa.config radxa_custom.config`；新增 0004/0005 config patch；DWC3 patch 针对 7.0.2 重写

## Impact

**代码层**
- `builder/rootfs.py`：新增 `_setup_extra_apt_sources()` 方法（基类，约 35 行）
- `builder/platforms/qualcommqcs6490/rootfs.py`：`_build_phase1` 调用新方法
- `builder/platforms/qualcommqcs6490/kernel.py`：`reset_source` 覆盖加 `git clean -fd`（修复同 commit 重建时 new-file 补丁重复应用失败）
- `docker/Dockerfile`：`gnupg` 加入 apt install 列表，需重建 Docker 镜像

**配置层**
- `components/platform/qualcommqcs6490/qcs6490/config.py`：branch+commit / defconfig（四段）/ enable_configs / disable_configs / rootfs.extra_apt_sources / rootfs.+packages

**Patch 层**
- `components/platform/qualcommqcs6490/patches/kernel/`：重写 0001（DWC3）、新增 0004（radxa.config）+ 0005（radxa_custom.config）；0002/0003 保持不变

**非目标**
- Venus 硬件编码验证：7.0.2 使用 mainline `vpu20_p1.mbn`（2MB），是否支持编码需实板验证，不在本变更范围内保证
- AIC8800 驱动升级：现有 cfg80211 兼容 patch 对 7.0 有效，驱动 commit 不变
- 魅族 E3 panel OOT 模块：内核 API 未变，不受影响
