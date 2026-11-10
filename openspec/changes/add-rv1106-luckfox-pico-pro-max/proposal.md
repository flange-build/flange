## Why

Alpine 发行版层需要一块真实硬件作为首个验收对象。Luckfox Pico Pro / Max（RV1106G2/G3，
单核 Cortex-A7，128/256 MB DDR3L，256 MB SPI NAND）资源紧张，正是 musl + OpenRC + busybox
相对 Ubuntu 有明显收益的场景。板级支持（BSP）与发行版无关，按 Yocto 的 BSP / distro 分离原则
放在 flange 核心，Alpine 层只在其上追加发行版产品。

仓库已有的 Rockchip 源码已覆盖 RV1106 全链路，无需引入新源：
- `flange-build/kernel @ linux-6.1-stan-rkr5.1` 含 `rv1106.dtsi`、`rv1106g3.dtsi`、`rv1106_defconfig`、
  `rv1106-nand.config`；
- `radxa/u-boot @ next-dev-v2026.01` 含 `rv1106_defconfig`；
- `radxa/rkbin @ develop-v2026.01` 含 `RKBOOT/RV1106MINIALL.ini` 与 `rv1106_ddr_924MHz_v1.15.bin`。

## What Changes

- 新增 SoC 层 `components/platform/rockchip/rv1106/config.jsonnet`：ARM32（`architecture.kernel/bootloader=arm`，
  `userspace=armhf`），沿用 rk3506b 的 gcc-10.3.1 ARM 工具链、vendor FIT boot、`boot_merger` idblock 路线，
  Kconfig 基线 `rv1106_defconfig` + `rv1106-nand.config`。
- 新增板级 `components/board/luckfox-pico-pro-max/`：
  - 内核补丁新增 `rv1106g-luckfox-pico-pro-max.dts`，由 Luckfox 官方 SDK（5.10）移植到 6.1 树；
    首版保留 SFC SPI NAND、以太网、USB OTG（peripheral）、SDMMC、ADC/TSADC、LED、RTC，
    不含摄像头/ISP/NPU 与 SDK 私有 DHT11 节点；`chosen.bootargs` 指定 UBI rootfs 与 `ttyFIQ0`。
  - 分区对齐官方 SPI NAND 布局：`env 256K`、`idblock 256K@256K`、`uboot 512K`、`boot 4M`，
    其余空间合并为 `rootfs`（UBI），不保留官方 `oem`/`userdata` 分区。
  - `storage: spinand`、`flash_identity`、UBI 几何、`recovery.enabled=false`。
  - 默认 product 为最小 Ubuntu armhf（只用于独立验证 BSP），Pro 与 Max 共用同一配置。
- 新增知识库 `wiki/boards/luckfox-pico-pro-max.md`。

## Capabilities

### New Capabilities
- `rockchip-rv1106-luckfox`: RV1106 SoC 构建通路与 Luckfox Pico Pro/Max 板级启动契约。

### Modified Capabilities
（无：沿用 `rockchip-arm32-spinand-ubi` 的 ARM32 + SPI NAND + UBI 路由。）

## Impact

- 只新增内容层文件，不改 `builder/` 代码；若 RV1106 暴露 rk3506b 未覆盖的平台差异，
  在任务中单独评估并补 golden 测试。
- 刷写走现有 Rockchip MaskROM 流程；实机目测由用户完成，结论写入 verification.md。

## 非目标

- 摄像头、ISP、NPU（RKNN）、硬件编解码、音频编解码器。
- 官方 SDK 的 Buildroot 用户态、`oem`/`userdata` 分区与 SD 卡启动。
- recovery 系统、A/B、userdata 迁移。
