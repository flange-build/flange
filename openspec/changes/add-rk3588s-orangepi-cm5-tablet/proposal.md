## Why

flange 已通过 `add-rk3588-radxa-rock5b` / `add-rk3588-orangepi-5-plus` 在 RK3588 上完成 SoC-level 抽象的两轮验证（rock5b 起底、opi5plus 仅复用 board 模板），但 RK3588S 通路自 `add-rk3588-radxa-rock5b` 引入以来一直是 SoC 占位状态——`components/platform/rockchip/rk3588s/config.py` 既无实板验证，也未与 in-tree Rockchip bcmdhd 驱动栈对接。OrangePi CM5 Tablet 形态板基于 RK3588S，板载 AP6256（BCM4345C5 模组、SDIO WiFi + UART BT）—— 这是与 `orangepi-cm4`（RK3566 + AP6256）**完全同源**的 WiFi/BT 套件，板级配置可直接复用 cm4 的 `+extra_firmware` 字段。新增该 board 同时落地两件事：① 验证 RK3588S SoC 通路可端到端跑通；② 在 RK3588 / RK3588S 双 SoC 上完成 AP6256 与 RTL8852BE 两套主流 WiFi 模组的覆盖。

## What Changes

- **新增 board `orangepi-cm5-tablet`**：`components/board/orangepi-cm5-tablet/config.py`，绑定 `soc=rk3588s`、`platform=rockchip`、`kernel.dts="rk3588s-orangepi-cm5-tablet"`；WiFi/BT 字段（`rootfs.+extra_firmware/radxa`）逐字段复用 `orangepi-cm4` AP6256 三件套配置（值相同，仓库相同，文件相同）。
- **新增 board overlay**：`overlay/etc/hostname`（内容 `orangepi-cm5-tablet`）；不携带 `usbdevice.conf`（cm4 也未配置，rkr5.1 generic 路径不需要）。
- **不携带板级 dtso / board_overlays**：argon kernel `linux-6.1-stan-rkr5.1` 已含完整 `rk3588s-orangepi-cm5-tablet.dts` 与配套 `-tablet-lcd.dtsi` / `-tablet-camera*.dtsi`（首版均不启用，靠 dts 默认 disabled 状态自然屏蔽）。
- **携带 1 条板级 kernel patch**：`patches/kernel/0001-bcmdhd-set-fw-ampak-path-brcm.patch`，逐字节复用 `orangepi-cm4/patches/kernel/0002-bcmdhd-set-fw-ampak-path-brcm.patch`。该 patch 修改 in-tree Rockchip bcmdhd 的 `Makefile`，启用 `FW_AMPAK_PATH="brcm"` 让驱动按 `/lib/firmware/brcm/<file>` 查找 AP6256 三件套——这是与 firmware 部署路径（`dest="lib/firmware"` + `repo_subdir="radxa-firmware/lib/firmware"` 含 `brcm/` 前缀）配套的硬约束，cm4 已实证。**不携带** cm4 的 `0001`（dtsi bootargs 修改针对 RK3566 cm4 dtsi、与 RK3588S cm5-tablet dts 不通用）与 `0003`（NPU disable 是否在 cm5-tablet 上需要由 apply 阶段 dmesg 判断）。
- **不携带板级 bcmdhd fragment**：SoC 层 `kernel.defconfig` fragment 链由首发的 cm4 板路径验证（in-tree Rockchip bcmdhd 通过 Kconfig `default y` 链自动启用）；cm5-tablet 上 apply 阶段若实测未启用，由 SoC 层补 fragment 而非 board 层私有覆盖。
- **不携带板级 u-boot defconfig**：radxa `u-boot next-dev-v2026.01` 中**无** `orangepi-cm5-tablet` 专属 defconfig，沿用 SoC 层 generic `rk3588_defconfig`。已核实邻近板（`radxa-cm5-io-rk3588s_defconfig` / `rock-5a-rk3588s_defconfig`）存在，可作 fallback 备胎。
- **新增知识库条目** `wiki/boards/orangepi-cm5-tablet.md`，并在 `wiki/boards/index.md` 添加索引项（项目惯例）。
- **零改动** `builder/`、`components/platform/rockchip/`（含 `rk3588s/config.py`）、其他 board 配置；lunch target `orangepi-cm5-tablet-default-{debug,release}` 由现有 product/variant 机制自动生成。

## Capabilities

### New Capabilities

- `rockchip-orangepi-cm5-tablet`：OrangePi CM5 Tablet（RK3588S）板级配置契约，定义 board config 各字段的取值约束（`soc=rk3588s`、`platform=rockchip`、`kernel.dts="rk3588s-orangepi-cm5-tablet"`、AP6256 SDIO WiFi + UART BT 走 in-tree Rockchip bcmdhd / btbcm 链路、不携带板级 dtso / board_overlays / 板级 patch / 板级 u-boot defconfig）、overlay 文件契约（仅 `hostname`）、以及板级零覆盖 SoC 层 GPU / defconfig / bootloader / partitions 字段的约束。

### Modified Capabilities

（无 — 本变更不修改任何现有 spec 的 requirement。SoC 层 `rockchip-platform` capability 由 `add-rk3588-radxa-rock5b` 引入并涵盖 RK3588S，本变更纯增量。）

## Impact

- **代码层**：零改动（`builder/` 完全不动）。
- **内容层**：
  - 新增 `components/board/orangepi-cm5-tablet/config.py` + `overlay/etc/hostname` + `patches/kernel/0001-bcmdhd-set-fw-ampak-path-brcm.patch`。
  - 不新增 `dtso/`。
- **外部依赖**（已核实，2026-05-17 git ls-remote / ls-tree 实测）：
  - argon kernel `linux-6.1-stan-rkr5.1`（HEAD `cf92049a`）已含 `arch/arm64/boot/dts/rockchip/rk3588s-orangepi-cm5-tablet.dts` 及配套 dtsi。
  - argon kernel 已含 in-tree Rockchip bcmdhd（`drivers/net/wireless/rockchip_wlan/rkwifi/bcmdhd/`），Kconfig `BCMDHD default y` 在 `WL_ROCKCHIP=y` 下自动启用。
  - radxa `u-boot next-dev-v2026.01`（HEAD `2742c75c`）含 generic `rk3588_defconfig`；无 `orangepi-cm5-tablet` 专属 defconfig，但有 `radxa-cm5-io-rk3588s_defconfig` 等邻近板 defconfig 可作 fallback 备胎。
  - WiFi/BT 固件：复用 cm4 已配置的 `radxa-pkg/radxa-firmware` 三件套（`fw_bcm43456c5_ag.bin` / `nvram_ap6256.txt` / `BCM4345C5.hcd`）。
- **回归范围**：现有 RK3588(S) 板（`radxa-rock5b` / `radxa-rock5c-lite` / `orangepi-5-plus`）必须验证 lunch target / 构建产物 / 内容哈希均不受影响（新增板目录哈希仅触发本板组件 build，他板产物 byte-identical）。
- **Flash 工具链**：完全复用 `RockchipFlashStrategy`，零改动；rk3588s rkbin 配置与 rk3588 一致（同 die 同 BootROM）。
- **lunch target**：`orangepi-cm5-tablet-default-debug` / `orangepi-cm5-tablet-default-release` 自动生成，无 CLI 改动。
- **RK3588S 通路首次实板验证**：本变更同时承担 SoC 层 `rk3588s/config.py` 端到端验证职责——之前仅 `radxa-rock5c-lite` 走 RK3582（同 die，复用 RK3588S dts），从未有原生 RK3588S 板穿过 u-boot → kernel → rootfs 全链路。验证失败可能反推 SoC 层调整（例如 generic `rk3588_defconfig` 兜底失败需补板级 defconfig 或退到 `radxa-cm5-io-rk3588s_defconfig`）。

## Non-Goals

- **不**点亮板载 DSI LCD 屏：argon kernel 已含 `rk3588s-orangepi-cm5-tablet-lcd.dtsi`，但首版不引入对应 panel driver / backlight 配置，与 cm4「DSI 屏不在首版范围」策略对齐。
- **不**支持触屏控制器：cm5 tablet 形态板通常配 GT911 / FocalTech I2C 触屏，首版不配置。
- **不**支持电池 / 充电 PMIC 与电源管理：tablet 形态特有的电池子系统（charger IC / fuel gauge / G-sensor）首版不配置，靠 5V Type-C 输入持续供电。
- **不**支持板载 MIPI CSI 相机：dts 中 camera1/2/3 dtsi 全部 disabled，首版不引入相机驱动栈。
- **不**支持 NPU：板级不覆盖 SoC 层 NPU 状态（沿用 SoC 层默认）；若上电出现 cm4 同款 NPU 启动 panic，由后续独立 change 处理（参考 cm4 `patches/kernel/` 现成 patch 模式）。
- **不**支持 NVMe / SATA / SD 启动：仅走 eMMC，与 rock5b / opi5plus 首版对齐。
- **不**支持 HDMI 输出 / GPU 图形栈 / VPU 编解码：panthor 驱动 + mali-csf firmware 由 SoC 层 `rk3588s/config.py` 部署，但首版不做图形栈端到端验证。
- **不**新增板级 dtso 或 board_overlays：rkr5.1 dts 自带 `arm,mali-valhall-csf` compatible，cm5-tablet 与 opi5plus 同样不携带 mali-valhall-compat emergency rollback dtbo。
- **不**移植 cm4 全部 3 条板级 patch：仅携带 `0002 bcmdhd FW_AMPAK_PATH="brcm"`（共享 in-tree bcmdhd Makefile 修改，AP6256 firmware 路径硬约束，cm4 已实证）；**不**携带 `0001`（dtsi bootargs，文件路径针对 RK3566 cm4 dtsi，与 cm5-tablet dts 不通用）；**不**携带 `0003`（NPU disable，cm5-tablet dts 上 NPU 状态未知，apply 阶段 dmesg 判断后决定是否补独立 change）。
- **不**新增板级 bcmdhd fragment：in-tree Rockchip bcmdhd 启用走 Kconfig `default y` 链，与 cm4 实测路径一致；若 cm5-tablet 上 fragment 缺失导致 bcmdhd 未编入，由 SoC 层补 fragment（潜在影响 cm4，需同回归）而非 board 层私有覆盖。
- **不**新增板级 u-boot defconfig：沿用 SoC 层 generic `rk3588_defconfig`；若上电 SPL/U-Boot 阶段失败，先尝试切到 `radxa-cm5-io-rk3588s_defconfig`（apply 阶段决策），最后才考虑 patch 新 defconfig。
- **不**新增 SoC 家族中间继承层：board 层完整复制 cm4 的 `+extra_firmware/radxa` 字段值，deep_merge 路径不变；当出现第三块 AP6256 板或第二块 RK3588S 板时再考虑是否抽象 AP6256 / RK3588S 中间层。
- **不**重命名或修改 cm4 / opi5plus / rock5b / rock5c-lite 任何字段：本变更纯增量。
- **不**调整 RK3588S partitions 偏移：沿用 SoC 层布局。
- **不**支持 Android / multi-OS 引导：仅走标准 extlinux.conf 流程。
