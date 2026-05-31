## Context

flange qcs6490 当前内核基线为 radxa/kernel@linux-6.18.2。本次探索（详见 explore 会话记录）对 linux-7.0.2 做了全面调研，结论如下：

**内核层变化**
- linux-7.0.2 QCS6490 DTS 将 `#include "sc7280.dtsi"` 改为 `#include "kodiak.dtsi"`（功能等价，kodiak.dtsi 内含 sc7280 内容）
- `video_mem` 区域从 8MB（6.18.2 调试 patch 遗留）→ 5MB（upstream 7.0.2）
- 现有三个 kernel patch 中：0002/0003（DTS 改动）可直接 apply（dry-run offset 通过）；0001（DWC3 clear-stall）需针对 7.0.2 行号重写，修复逻辑不变

**Config 策略**
- linux-qcom 官方仓库（radxa 维护，构建 linux-image-radxa-dragon-q6a deb）使用**四段叠加**配方 `defconfig qcom_module.config radxa.config radxa_custom.config`（见其 `.github/local/Makefile.local` 的 `KERNEL_DEFCONFIG`）
- `qcom_module.config` 是 mainline `arch/arm64/configs/` 下软链到 radxa `radxa_qcom_7_0_defconfig` 的 qcom 全量平台 config（数百项 qcom 驱动 =y）；radxa.config(1101 行)/radxa_custom.config(14 行) 为 Radxa 通用/自定义片段；均 `make <name>.config` 触发 `merge_config.sh` 合并
- flange 构建器 `configure()` 已支持 `defconfig: list` 格式，天然兼容四段叠加
- ⚠️ 实施修正：最初只对齐了 `defconfig radxa.config`（漏 `qcom_module.config`），实板 UFS probe 早期被 QHEE PSHOLD 整机复位；补齐四段后正常（详见决策 1）

**VPU 固件**
- 7.0.2 venus 驱动加载 `qcom/vpu-2.0/venus.mbn`，对应 mainline `vpu20_p1.mbn`（2MB，远低于 5MB DTS 限制）
- 以前的"7MB 固件"是 BSP 时代历史遗留，与 mainline 路线无关
- ubuntu-qcom-iot/qcom-ppa 提供 `linux-firmware-dragonwing`，包含 QCS6490 ADSP/CDSP/GPU 固件更新（置于 `/lib/firmware/updates/` 优先级路径）

**AIC8800 WiFi**
- 7.0.2 cfg80211 API 与 6.18 一致，现有 `>= 6.18.0` 版本守卫对 7.0 有效，无需新 patch

## Goals / Non-Goals

**Goals:**
- 内核基线升至 linux-7.0.2，与 Radxa 官方 linux-qcom 包对齐
- 采纳 radxa.config 作为第二层 defconfig，获得 Radxa 测试覆盖的 config 取舍（DMABUF_HEAPS 等 GPU/媒体 pipeline 必要项）
- 为 flange rootfs 构建器增加通用 `extra_apt_sources` 能力，安装 Qualcomm IoT PPA 固件包
- 所有现有功能（ADB、WiFi、魅族 E3 屏）在 7.0.2 继续工作

**Non-Goals:**
- Venus 硬件编码：mainline firmware 是否支持编码需实板验证，本变更不保证
- Docker 镜像立即重建：Dockerfile 改动需手动 `docker compose build`

## Decisions

### 决策 1：内核 config 完全对齐 radxa rsdk 四段配方（含根因修正）

**选择**：用 radxa rsdk/linux-qcom 的确切配方 `defconfig qcom_module.config radxa.config radxa_custom.config` 替代自研裁剪。

**根因（实板定位）**：最初只对齐 `defconfig radxa.config` + 手工 cherry-pick 少量 UFS/PHY `enable_configs` 强制 builtin，**漏掉了 `qcom_module.config`**（radxa `radxa_qcom_7_0_defconfig` 的 qcom 全量平台 config）。于是 `QCOM_QSEECOM`/`QSEECOM_UEFISECAPP`、`QCOM_AOSS_QMP`（资源/电源握手）、`QCOM_LLCC`、`ARM_SMMU_V3`、`QCOM_IOMMU`、`QCOM_PDC`/`MPM`、`RESET_QCOM_AOSS` 等一整批 qcom 平台驱动缺失；UFS bring-up 依赖这些做资源/电源/IOMMU 托管，驱动缺位 → 访问未就绪/未授权资源 → 安全侧（QHEE/Gunyah）`PM: Reset by PSHOLD` 整机复位、无 kernel oops。补齐四段后 UFS 正常（rootfs 挂 `/dev/sda2`，Samsung 128G UFS）。

**理由**：
- 自研 cherry-pick 少数 CONFIG 替代上游整张 qcom defconfig 必然漏依赖；QHEE 硬复位无 oops，几乎无法从内核侧定位，只能对齐可工作参考系（rsdk）
- 内核源码与 radxa 生产逐字相同（7.0.2-2 src 子模块 = commit `7473a9f`，而 broken 的 `linux-7.0.2` 分支 tip 是 `6445af0c5`）→ 单 pin commit 无效，**必须对齐 config 配方**
- 四段顺序由 radxa 固定（后者覆盖前者）；flange 按同序叠加，行为一致可预期

**保留项**：`enable_configs` 收敛为 flange 特定补充（`FW_LOADER_COMPRESS*`、USB gadget configfs/F_FS——qcom_module.config 未覆盖）；`disable_configs` 仅保留 `MODULE_SIG_FORCE`。

**配套**：① `repos.kernel` pin `commit=7473a9f`（= radxa 7.0.2-2）；② `Qcs6490KernelBuilder.reset_source` 覆盖加 `git clean -fd`，否则同 commit 重建时未跟踪的 radxa.config/radxa_custom.config 残留会让 new-file 补丁二次 apply 报 `already exists`；③ **刷新 SPI EDK2/XBL 固件**到 `260120`（`flange flash --spi-firmware`）——旧固件（`251013`/00364-KODIAKLA）↔ kodiak DTB 资源/握手不匹配是 UFS 复位的**第二个必需修复**；实板坐实：仅补 config 时慢启动（调试串拖慢）侥幸过、干净快启动复位，刷固件后干净启动也正常。

---

### 决策 2：extra_apt_sources 作为 RootfsBuilder 基类方法

**选择**：在 `builder/rootfs.py` 基类新增 `_setup_extra_apt_sources()`，在 qcs6490 `_build_phase1` 的 `apt-get update` 之前调用。

**理由**：
- qcom-ppa 是 apt 仓库，所有依赖自动解析；`dpkg -i` 方式不处理依赖链
- `extra_apt_sources` 是通用能力，未来其他平台（如需要 ARM 商业仓库）可复用
- 实现约 35 行 Python，代价低

**实现**：在 Phase 1 chroot 创建之前（tarball 解压后），用 Python 写 `sources.list.d/<name>.list`，用 `docker.run sh -c "curl ... | gpg --dearmor"` 写 keyrings 目录，keyrings/sources 均落在 rootfs_dir 内，Phase 1 的 `apt-get update` 即可找到新源。

**Dockerfile 依赖**：需在构建镜像中加 `gnupg`（用于 `gpg --dearmor`）。

**配置格式**：
```python
"extra_apt_sources": [
    {
        "name": "qcom-ppa",
        "key_url": "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x<fp>",
        "source": "deb [arch=arm64 signed-by=/etc/apt/keyrings/qcom-ppa.gpg] https://... noble main",
    }
]
```

---

### 决策 3：DTS patch 0002/0003 原样保留，0001 重写

**选择**：0002（USB1 peripheral）和 0003（i2c13 drop gsi-dma）不重新生成，直接复用；0001（DWC3 gadget clear-stall）重写。

**理由**：
- 0002/0003 dry-run 验证通过（offset +8/+1 行），git patch context 匹配
- 0001 修复的代码在 7.0.2 中行号变化较大（2342 → 2247），且我们当前 .build/sources 中的 0001 版本带有调试 `VENUSDBG` log，是临时 patch 不应进代码库；重写更干净

---

### 决策 4：radxa.config / radxa_custom.config 以 kernel patch 形式注入

**选择**：将 radxa 两个 config 片段封装为 flange kernel patch——`0004-feat-radxa-common-kernel-config.patch`（radxa.config）、`0005-feat-radxa-custom-kernel-config.patch`（radxa_custom.config），内容拷贝自 `ref/linux-qcom/debian/patches/linux/` 的 `0001`/`0002`，**路径去掉 radxa 的 `src/` 前缀**（flange 在内核树根打补丁，radxa 在 submodule `src/` 下）。`qcom_module.config` 为内核 in-tree（软链 `radxa_qcom_7_0_defconfig`），无需 patch。

**理由**：与其他平台 kernel patch 管理方式一致；`git apply` 后 `arch/arm64/configs/{radxa,radxa_custom}.config` 存在，`make <name>.config` 即可触发合并。注意 new-file 补丁需配合 `reset_source` 的 `git clean`（见决策 1 配套），避免同 commit 重建残留冲突。

## Risks / Trade-offs

| 风险 | 缓解 |
|------|------|
| 7.0.2 DTS `kodiak.dtsi` 引入新的节点依赖，0002/0003 patch context 不匹配 | dry-run 已验证；构建期 git apply 失败会立即报错，不会静默跳过 |
| radxa.config 开启了 DRM_AMDGPU/NOUVEAU 等大模块，编译时间增加 | radxa.config 整体 config 取舍与我们的裁剪列表效果相当；可接受 |
| ubuntu-qcom-iot/qcom-ppa keyserver 网络超时 | `curl -fsSL` 失败即报错，构建终止，不会生成无固件镜像 |
| Docker 镜像需重建（加 gnupg）| 一次性操作，与镜像版本管理无关 |
| Venus 编码在 7.0.2 实板表现未知 | 本变更不保证编码；解码路径明确可用 |

## Migration Plan

1. 重建 Docker 镜像（`docker compose build`）
2. 清除旧 kernel 构建缓存（`.build/sources/repos/kernel/` 或全量 clean）
3. `flange build` 触发完整构建
4. 实板验证：ADB / GPU / WiFi / 触摸屏 / 解码

**回滚**：改动均在 config.py + patches/ 层面，git revert 即可；旧 linux-6.18.2 分支由 radxa 保留，不会消失。

## Open Questions

- ~~Venus 编码~~（已答 2026-05-31，实板 7.0.2）：mainline `vpu20_p1.mbn` **不支持** QCS6490 硬件 H.264 编码——`v4l2h264enc` 喂帧即整机复位（TZ/CP 契约），硬件解码正常。详见记忆 `qcs6490-venus-encode-soc-reset`
- `linux-firmware-dragonwing` 依赖链：该包是否依赖 `linux-firmware >= X`？构建时如需降级处理需确认
