## Context

现有 Amlogic 平台已经支持 mainline U-Boot/Linux、LibreELEC FIP、pyamlboot → fastboot 刷写和
extlinux 启动。Khadas VIM3 与 VIM3L 共用 `meson-khadas-vim3.dtsi` 描述的大部分板载外设，但 SoC family、
Device Tree（设备树）和 FIP（Firmware Image Package，固件镜像包）加密工具不同：VIM3 是
A311D/G12B，必须使用 `aml_encrypt_g12b`，不能把它伪装成 S905D3/SM1 板。

本地固定版本源码已核实：U-Boot v2024.10 含 `khadas-vim3_defconfig`，Linux v6.12 含
`meson-g12b-a311d-khadas-vim3.dts`，`amlogic-boot-fip/khadas-vim3/Makefile` 指定
`aml_encrypt_g12b`。VIM3 和 VIM3L 的 U-Boot eMMC 均枚举为 `mmc2`。
该 Makefile 共用 `g12a.inc`，其中 `--bootmk` 已一次生成 FIP、SD 与 USB 四件产物；G12B 工具不支持 builder
原先重复调用的 `--bootsd` / `--bootusb` 接口。

## Goals / Non-Goals

**Goals:**

- 通过既有自动发现提供 `khadas-vim3-{default,desktop}-{debug,release}` target。
- 复用 Amlogic builder/flash，不增加板级平台分支；修正共享 builder 的 FIP 产物契约。
- 保持 VIM3L 现有 canonical 配置语义不变，同时复用两板相同的 AP6398S、内核选项和 eMMC 数据。
- 用配置测试锁定 A311D、DTB、U-Boot defconfig、FIP board/tool 和 target 枚举。

**Non-Goals:**

- 不适配 NPU、VPU、PCIe/USB3 MCU 切换或 SPI NOR 启动。
- 不引入 Khadas vendor kernel/U-Boot。
- 没有实板时不宣称 VIM3 或 V14 硬件已完成刷写验收。

## Decisions

### 1. A311D 使用独立 SoC 层

新增 `components/platform/amlogic/a311d/config.jsonnet`，结构沿用 S905D3，但使用独立 source 名和
`fip_tool = "aml_encrypt_g12b"`。不从 `s905d3` 配置 import 后改名，因为那会把 SM1 芯片事实和误导性的 source
身份带入 G12B。

### 2. 复用 Amlogic 策略并按 build-fip 产物契约收集

板层选择 `khadas-vim3_defconfig`、`meson-g12b-a311d-khadas-vim3` 和 `khadas-vim3` FIP 目录；其余编译、
extlinux 和 USB Burning 流程均由配置驱动。`build-fip.sh` 的 board Makefile 已通过 `aml_encrypt_* --bootmk`
生成 `u-boot.bin`、`.sd.bin`、`.usb.bl2` 和 `.usb.tpl`，builder 只收集这些产物，不再调用 family 工具的
非通用二次派生接口；无需增加新的 flash strategy。

### 3. fastboot fragment 放在板层

VIM3 的 eMMC 在 mainline U-Boot 中是 `mmc2`，因此 fragment 沿用现有 boot0/GPT/PREBOOT 配置。
MMC 枚举和 user-area 分区属于板级存储拓扑，文件放到
`components/board/khadas-vim3/patches/bootloader/`，避免把单板假设固化为所有 A311D 板的 SoC 事实。

### 4. 提取 VIM3 系列共享 Jsonnet 数据

把 VIM3/VIM3L 完全相同的 AP6398S source/firmware、Binder/TUN 内核选项、products/variants 和 eMMC 分区布局
放入一个 `components/config/` helper。两块板仍分别声明 identity、DTB、defconfig、FIP 目录与 SPI overlay，
避免板对板继承导致未来的 VIM3L 专属修改静默污染 VIM3。

分区布局留在 board 共享 helper，不放入 A311D SoC 层；存储路由不是芯片级事实。

BT 不新增 `btattach` service：两块板共用的 mainline DTS 已声明 Bluetooth serdev 子节点，内核可自动绑定；
现有 VIM3L service 未启用，不作为新板依赖。

### 5. SPI overlay 保持 VIM3L 功能对齐

VIM3 与 VIM3L 共用 G12 common 的 `spicc1` 和 pinctrl symbols，故为 VIM3 提供同形的板私有 overlay；不跨板引用
VIM3L 文件，因为 overlay builder 固定从当前 `components/board/<board>/dtso/` 取源。

## Risks / Trade-offs

- [VIM3 V14 更换 DRAM 后可能与旧 FIP blob 不兼容] → 保留 LibreELEC VIM3 专属 blob，不复用 VIM3L blob；将 V14
  刷写列为实板验收项，失败时单独更新 FIP 来源。
- [`amlogic-boot-fip@master` 与 `khadas/fenix@master` 可变] → 本次保持既有 Amlogic 依赖策略，不额外扩大迁移；
  后续需要完全可复现时统一锁 commit。
- [无实板只能验证配置与构建输入] → 文档明确标记待实测，不把单元测试等同于硬件验收。

## Migration Plan

这是纯增量 target。合入后直接执行 `lunch khadas-vim3-default-debug`；回滚时删除 VIM3/A311D 新目录并还原共享
VIM3 系列配置引用，不涉及已有产物格式或用户数据迁移。

## Open Questions

无；V14 DRAM 兼容性留给实板验收给出结论。
