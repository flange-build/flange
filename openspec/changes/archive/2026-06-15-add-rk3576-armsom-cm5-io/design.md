## Context

flange 的 rockchip 平台已支持两代 SoC：RK356x（rk3566/rk3568，闭源 mali_kbase）
与 RK3588/RK3588S（已切 mainline panthor 开源 GPU）。本变更新增第三代 RK3576，
目标板为 ArmSoM CM5 IO。关键约束：

- 内核沿用 RK3588 同款 argon BSP `linux-6.1-stan-rkr5.1`。该分支是**全 SoC BSP
  树**，已自带 RK3576 全套 dts、驱动与 Kconfig，无需引入新内核源。
- RK3576 GPU 为 **Mali-G52 MC3（Bifrost 架构，无 CSF）**，与 RK3588 的
  Mali-G610（Valhall-CSF）不是同一类硬件。
- 用户要求 GPU 走**开源驱动**，且"整体配置对齐 rk3588"。
- `rk3576-armsom-cm5-io.dts` 及配套 dtsi 已在 BSP 树内并已提交，但 armsom 全系
  未进 `Makefile`，故不产出 dtb。

## Goals / Non-Goals

**Goals**
- RK3576 SoC 数据层 + ArmSoM CM5 IO board 数据层接入 flange 构建链。
- GPU 走开源 panfrost，关闭闭源 mali_kbase。
- 复用现有 rockchip 平台构建策略（kernel/bootloader/image/rootfs），只做配置化
  扩展，不改框架层。

**Non-Goals**
- 不支持 CM5 的 `rpi-cm4-io` 变体板（后续单独变更）。
- 不纳入 HDMI/MIPI 屏/摄像头/音频/蓝牙/Wi-Fi/NPU/VPU 验收。
- 不改动 RK3588 panthor 现有路线，不重构配置继承 / engine / flash。

## Decisions

### 决策 1：GPU 开源驱动选 panfrost，而非照搬 rk3588 的 panthor

"对齐 rk3588"对齐的是**方法论**（关闭闭源 kbase + 启用 mainline DRM 驱动 +
config fragment 机制），而非驱动本身。驱动按 SoC 的 GPU 架构选：

| | RK3588 | RK3576 |
|---|---|---|
| GPU | Mali-G610（Valhall，有 CSF） | Mali-G52（Bifrost，无 CSF） |
| 开源驱动 | panthor | **panfrost** |
| dts compatible | `arm,mali-valhall-csf` | `arm,mali-bifrost`（已是） |
| CSF firmware | 需 `mali_csffw.bin` | **不需要** |

依据：`panthor_drv.c` of_match 只认 `arm,mali-valhall-csf` /
`rockchip,rk3588-mali`，物理上带不动 G52；`panfrost_drv.c:684` of_match 认
`arm,mali-bifrost`，而 `rk3576.dtsi` 的 `gpu@27800000` compatible 恰为
`arm,mali-bifrost`，天然对位。

**被否方案**：直接套用 rk3588 的 `rk3588_panthor.config` fragment。不可行——
`_write_panthor_fragment` 对非 rk3588/rk3588s 的 SoC 生成**空 fragment**，
RK3576 会退回默认 `CONFIG_MALI_BIFROST=y`（闭源 kbase），与"开源 GPU"诉求相反。

### 决策 2：新增独立的 `_write_panfrost_fragment`，不泛化合并

在 `builder/platforms/rockchip/kernel.py` 新增 `_write_panfrost_fragment`，
与 `_write_panthor_fragment` 同构：仅对 `soc in (rk3576,)` 生成实质内容
（关 `CONFIG_MALI_BIFROST`/`CONFIG_MALI_MIDGARD` 等 kbase + 关 utgard
mali400/450 + 开 `CONFIG_DRM_PANFROST=y`），其余 SoC 写空 fragment。SoC config
的 `kernel.defconfig` list 追加 `rk3576_panfrost.config`。

**被否方案**：把 panthor/panfrost 合并成一个 `_write_gpu_fragment`。否决理由：
panthor 函数已是既有稳定实现，合并会触碰 rk3588 回归面；保持两函数并列与现有
代码风格一致，新增零回归。

### 决策 3：内核源/分支/base defconfig 完全复用 rk3588

`kernel.repo` = argon kernel、`kernel.branch` = `linux-6.1-stan-rkr5.1`、
`kernel.defconfig` base = `rockchip_linux_defconfig`，与 rk3588 一致。差异仅在
fragment list（panthor → panfrost）。

### 决策 4：DTS 不迁移，只补 Makefile + 启用 GPU 节点

在 kernel-rockchip 仓库内：`Makefile` 增
`dtb-$(CONFIG_ARCH_ROCKCHIP) += rk3576-armsom-cm5-io.dtb`；确保 GPU 节点
`status="okay"`（位置见 Open Questions）。这部分独立在 kernel-rockchip 仓库提交。

### 决策 5：bootloader 用 rk3576 自己的 config，类比 rk3588

SoC 层 `rkbin.ini_prefix="RK3576"`、`mkimage_chip="rk3576"`、
`trust_ini_prefix="RK3576"`；`bootloader.repo`/`branch` 复用 radxa u-boot，
`bootloader.defconfig` 用 armsom-cm5-io 的 RK3576 defconfig。打包链路
（idbloader → u-boot.itb、BL31/DDR 解析）零改动。

### 决策 6：RK3576 走"打包 OP-TEE"而非"关闭 OPTEE client"（bring-up 实测，与其他 SoC 分歧）

bring-up 实测：generic `rk3576_defconfig` 启用 `CONFIG_OPTEE_CLIENT`（u-boot
proper 开机强制做 OP-TEE api revision 检查）但 SPL 未加载 OP-TEE，导致
BL31 报 `No OPTEE provided by BL2`、u-boot 在 `optee check api revision fail`
处 halt（`### ERROR ### Please RESET the board ###`）。

flange 既有惯例（platform 补丁 0003/0005）对 RK3566/RK3568/RK3588/RK3588S
一律"关闭 OPTEE_CLIENT 三件套"（Direction 2，不使用 OP-TEE）。本变更按用户
决策对 RK3576 采用 **Direction 1：真正把 OP-TEE 打进 FIT、保留 OPTEE_CLIENT、
OP-TEE 在板可用**。

实现为取消注释 `make_fit_atf.sh` 的 `gen_bl32_node`。**初版**置于
armsom-cm5-io 板级目录（patch 0002）；**按用户决策已提升为平台级**
`components/platform/rockchip/patches/bootloader/0006-rockchip-fit-uncomment-bl32-node.patch`，
使**全部 rockchip SoC**（RK3566/RK3568/RK3576/RK3582/RK3588/RK3588S）的
u-boot.itb 都打包 OP-TEE（各 SoC RKTRUST.ini 均含 BL32，tee.bin 由 flange
既有逻辑复制到位）。此举把变更范围从单板扩到全 rockchip 平台。

bring-up 第一次尝试曾另加 patch 0001（`rk3576_defconfig`
+`CONFIG_SPL_OPTEE=y`）但**编译失败**：该符号会拉入 armv7 专用汇编
`common/spl/spl_optee.S`（`mov pc,r3` / `.syntax`），arm64 SPL 编不过
（`common/spl/Makefile:56` 无 arch 门控）。查 `fit_args.sh`：`CONFIG_ARM64=y`
时生成器 `ARCH=arm64`，`gen_bl32_node` 内 `[ "${ARCH}" == "arm" ]` 分支被跳过
→ **arm64 根本不需要 `CONFIG_SPL_OPTEE`**，仅靠 `TEE_LOAD_ADDR` 非空即生成
optee 节点并设 `LOADABLE_OPTEE`（经 `gen_arm64_configurations` 接入 config
`loadables`，SPL 加载交 BL31）。故 0001 删除，仅留 0002。

`tee.bin` 由 flange 既有 bootloader 逻辑从 rkbin RKTRUST 的 BL32 复制到位；
`TEE_LOAD_ADDR` 由 u-boot `fit_args.sh` 默认计算（`DRAM_BASE + 0x08400000`）。
**flange Python 代码零改动。** 平台级 0006 生效后，全 rockchip 板 bootloader
缓存失效重建，u-boot.itb 均新增 optee 节点。

与 0003/0005（关闭 RK3588/RK3568 的 OPTEE_CLIENT）的关系：那两个 patch 当初
因"client 开着但 OP-TEE 未打包 → halt"而关 client；0006 已把 OP-TEE 打包，
halt 根因消除。**按用户决策（Option B）已删除 0003 与 0005**，恢复上游
defconfig 的 `CONFIG_OPTEE_CLIENT` 三件套 → 全 rockchip 平台统一 **full
Direction 1**：client 开 + OP-TEE 打包，u-boot 与内核均使用 OP-TEE，rk3576
与其余板行为一致。

副作用：删 0003/0005 改动 5 块 proven 板（rk3566/3568/3582/3588/3588s）的
u-boot 行为（"optee check api revision" 重新启用，现 OP-TEE 已在应通过），
需逐板 rebuild+flash 复测。wiki（`platforms/rockchip-平台.md` OPTEE 段、
`log.md`）描述已过时，待 `/sync-wiki` 同步。

遗留不一致：RK3576 成为平台内唯一启用 OP-TEE 的 SoC，其余仍 Direction 2。
若需统一（其余也打包 OP-TEE），应另起变更并逐板实测，不在本变更范围。

## Risks / Trade-offs

- **rkbin / u-boot 对 RK3576 的可用性**：✅ bring-up 已验证——generic
  `rk3576_defconfig`（radxa u-boot next-dev-v2026.01）+ rkbin `RK3576MINIALL.ini`
  /DDR/BL31 均可用，DDR init → SPL → BL31 → u-boot 全程正常。唯一卡点是
  OP-TEE 未打包（已由板级补丁 0001/0002 解决，见决策 6）。
- **panfrost 对 G52/RK3576 在 6.1 BSP 的运行时成熟度**：`DRM_PANFROST` 源码在
  树内，但 RK3576 在 6.1 BSP 上跑 panfrost 的实测稳定性需上板确认。
- **kbase 与 panfrost compatible 冲突**：两者都认 `arm,mali-bifrost`，必须确保
  fragment 切实关闭 kbase，否则两驱动抢同一节点。
- **改 SoC 公共 dtsi 的影响面**：若在 `rk3576.dtsi` 改 GPU `status`，会影响所有
  RK3576 板；倾向在板 dts 层 enable（见 Open Questions）。

## Migration Plan

纯增量，不触碰现有板：
- panfrost fragment 仅对 rk3576 SoC 生效，对 rk3566/rk3568/rk3588 写空 fragment。
- 新增 SoC/board config 文件与新增测试，不改既有 config。
- kernel-rockchip 的 Makefile/dts 改动只新增 armsom-cm5-io dtb 与启用其 GPU，
  不影响其它 dtb。

## Open Questions

- **GPU `status="okay"` 放哪里？** 需确认 `rk3576-armsom-cm5-io.dts` 是否已
  自带 `&gpu { status = "okay"; }`；若已有则无需改 dts，否则在板 dts（而非 SoC
  公共 `rk3576.dtsi`）补 enable。实施首步先核实。
- **rkbin `RK3576` ini 与 u-boot `armsom-cm5-io` defconfig 的确切名称**，
  bring-up 时按 radxa 仓库实际内容敲定。
- **panfrost 是否需补 mesa/userspace**：rootfs 侧 panfrost 用户态（mesa
  panfrost gallium）是否随 ubuntu-base 自带或需追加，首版验收若仅要求 GPU 节点
  probe 成功可暂不纳入。
