## Why

flange 已有 Khadas VIM3L 的 Amlogic 构建与刷写链路，但缺少同系列 Khadas VIM3（A311D / G12B）目标。
主线 U-Boot、Linux 和现有 FIP 仓库均已提供 VIM3 入口，因此可以复用现有 Amlogic 策略，仅补充 SoC 与板级数据。

## What Changes

- 新增 `a311d` SoC 配置，声明 mainline U-Boot/Linux 来源、G12B FIP（Firmware Image Package，
  固件镜像包）工具、通用内核配置和启动参数。
- 新增 `khadas-vim3` 板级配置，选择 `khadas-vim3_defconfig`、
  `meson-g12b-a311d-khadas-vim3` Device Tree（设备树）与 `khadas-vim3` FIP 目录。
- VIM3 与 VIM3L 共用 AP6398S Wi-Fi/BT、eMMC 和 product/variant 策略的 Jsonnet 数据；ADB gadget 与 SPI overlay 沿用相同板级模式。
- 通过现有自动发现和 Amlogic builder/flash 策略生成 lunch target；修正 bootloader builder，直接收集 `build-fip.sh` 已生成的四件产物。
- 补充 canonical 配置测试与板卡索引文档。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `amlogic-platform`：增加 A311D SoC 与 Khadas VIM3 板级配置、构建输入和自动发现要求。
- `amlogic-flash`：把进入 MaskROM 与 eMMC 设备选择改为板级契约，覆盖 VIM3 的 TST 三击和 `mmc2`。

## Impact

- 配置：`components/platform/amlogic/a311d/`、`components/board/khadas-vim3/`，以及 Khadas VIM3 系列共享 Jsonnet 数据。
- 构建器：删除不兼容 G12B 的重复 `--bootsd` / `--bootusb` 调用。
- 测试：canonical target 数量、VIM3 板级数据与 Amlogic bootloader 调用断言。
- 文档：README 与 wiki 板卡索引、VIM3 板级说明，并校正 Amlogic flash 规范的旧硬编码。
- 外部源码仍使用现有 `u-boot/u-boot@v2024.10`、`torvalds/linux@v6.12`、
  `LibreELEC/amlogic-boot-fip@master` 和 `khadas/fenix@master`，不新增 host 依赖。

## 非目标

- 不新增 Amlogic flash 策略，不改变主刷写顺序及 CLI。
- 不引入 vendor kernel/U-Boot，不单独适配 NPU、VPU、PCIe/USB3 MCU 切换或 SPI NOR 启动。
- 不把缺少实板条件的软件验证表述为实板验收结果。
