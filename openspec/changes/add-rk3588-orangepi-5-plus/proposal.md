## Why

flange 已通过 `add-rk3588-radxa-rock5b` 变更打通 RK3588 全链路（SoC config、platform patch、panthor GPU 路线、rkwifibt OOT 模式、mali-csf firmware 注入），SoC-level 抽象的红利尚未兑现。OrangePi 5 Plus 同样基于 RK3588，硬件外设（M.2 E-key RTL8852BE、Mali-G610、UART2 console、eMMC 启动）与 ROCK 5B 等价，仅 dts 与 hostname 不同。新增该 board 可在最小代价下扩充 RK3588 矩阵覆盖。

## What Changes

- **新增 board `orangepi-5-plus`**：`components/board/orangepi-5-plus/config.py`，绑定 `soc=rk3588`、`platform=rockchip`、`kernel.dts="rk3588-orangepi-5-plus"`；其余字段（kernel.oot_sources/rkwifibt、kernel.+oot_modules/rtl8852be、rootfs.+extra_firmware/rkwifibt-rtl8852be）完整复用 `radxa-rock5b` 同名字段，逐字段等价（值相同，文件不同）。
- **新增 board overlay**：`overlay/etc/hostname`（内容 `orangepi-5-plus`）、`overlay/etc/usbdevice.conf`（照搬 `radxa-rock5b` 同名文件）。
- **不复制 dtso 与 board_overlays**：rock5b 携带的 `mali-valhall-compat` emergency rollback dtso 不进入本板范围（SoC 层已切 mainline panthor 驱动，dts 自带 `arm,mali-valhall-csf` compatible 可直接绑 panthor；rock5b 至今未触发 rollback 需求）。`config.py` 不声明 `boot.board_overlays`，仅由 SoC 层 `boot.{dtb_overlays,vendor_overlays,default_overlays}` 控制。
- **新增知识库条目** `wiki/boards/orangepi-5-plus.md`，并在 `wiki/boards/index.md` 添加索引项（项目惯例）。
- **零改动** `builder/`、`components/platform/rockchip/`、其他 board 配置；lunch target `orangepi-5-plus-default-{debug,release}` 由现有 product/variant 机制自动生成。

## Capabilities

### New Capabilities

- `rockchip-orangepi-5-plus`: OrangePi 5 Plus（RK3588）板级配置契约，定义 board config 各字段的取值约束（`soc=rk3588`、`platform=rockchip`、`kernel.dts="rk3588-orangepi-5-plus"`、M.2 E-key RTL8852BE WiFi/BT 走 rkwifibt OOT 链路、不携带板级 dtso/board_overlays）、overlay 文件契约（hostname、usbdevice.conf）、以及板级零覆盖 SoC 层 GPU/defconfig/bootloader 字段的约束。

### Modified Capabilities

（无 — 本变更不修改任何现有 spec 的 requirement。SoC 层 `rockchip-platform` capability 由 `add-rk3588-radxa-rock5b` 引入，本变更纯增量。）

## Impact

- **代码层**：零改动（`builder/` 完全不动）。
- **内容层**：
  - 新增 `components/board/orangepi-5-plus/config.py` + `overlay/etc/{hostname,usbdevice.conf}`。
  - 不新增 `dtso/`、不新增 `patches/`。
- **外部依赖**（已核实）：
  - SoC 层指向的 `radxa/u-boot next-dev-v2026.01` 已含 generic `rk3588_defconfig`（OrangePi 5 Plus 不需要板级 defconfig，沿用 generic）。
  - SoC 层指向的 argon kernel `linux-6.1-stan-rkr5.1` 已含 `rk3588-orangepi-5-plus.dts`。
  - WiFi/BT：复用 SoC 层无新增，rkwifibt 仓库 `develop` 分支提供 RTL8852BE 驱动与固件（同 rock5b 路径）。
- **回归范围**：现有 RK3588 板（`radxa-rock5b`）必须验证 lunch target / 构建产物 / 内容哈希均不受影响（新增板目录哈希仅触发本板组件 build，rock5b 产物 byte-identical）。
- **Flash 工具链**：完全复用 `RockchipFlashStrategy`，零改动。
- **lunch target**：`orangepi-5-plus-default-debug` / `orangepi-5-plus-default-release` 自动生成，无 CLI 改动。

## Non-Goals

- **不**适配 OrangePi 5 Plus 板载特有外设：双 2.5G PCIe 网卡（`r8169` 主线驱动自动 probe，本变更无需配置）、双 HDMI 输出、4-lane MIPI CSI、PCIe Gen3 x4 M.2 M-key SSD、RGB LED、PWM 风扇 —— 首版验收仅 UART2 串口 + SSH。
- **不**支持 NVMe SSD 启动：仅走 eMMC，与 rock5b 首版对齐。
- **不**支持 HDMI 输出 / GPU 图形栈 / VPU 编解码：panthor 驱动 + mali-csf firmware 在 SoC 层已部署，但首版不做图形栈端到端验证。
- **不**新增板级 dtso 或 board_overlays：mali-valhall-compat emergency rollback dtso 不携带（rock5b 至今未触发 rollback，证明 panthor 路径稳定）。
- **不**新增板级 kernel/bootloader patch：所有 RK3588 通用问题（OP-TEE client 关闭、dtb bootargs 合并跳过、panthor 启用）已由 SoC 层与 platform 层 patch 解决。
- **不**新增 SoC 家族中间继承层：board 层完整复制 rock5b 的 oot_sources/+oot_modules/+extra_firmware 字段值，deep_merge 路径不变；当出现第三块 RK3588 板时再考虑是否抽象。
- **不**重命名或修改 rock5b 任何字段：本变更纯增量，rock5b 与其他板配置不动。
- **不**调整 RK3588 partitions 偏移：沿用 SoC 层布局，与 rock5b 同。
- **不**支持 Android / multi-OS 引导：仅走标准 extlinux.conf 流程。
