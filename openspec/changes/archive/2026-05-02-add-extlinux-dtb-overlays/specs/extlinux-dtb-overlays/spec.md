## ADDED Requirements

### Requirement: Device Tree Overlay 配置契约
平台、SoC、board 或 product 配置必须（SHALL）通过 `boot.dtb_overlays` 声明需要构建并打包的 Device Tree Overlay（设备树覆盖）文件列表，通过 `boot.default_overlays` 声明默认启动时需要应用的 overlay 文件列表。`default_overlays` 必须（MUST）保持声明顺序并作为 `dtb_overlays` 的子集。

#### Scenario: 声明多个默认 overlay
- **WHEN** 最终配置中 `boot.dtb_overlays == ["i2c1.dtbo", "spi1.dtbo", "display.dtbo"]` 且 `boot.default_overlays == ["i2c1.dtbo", "display.dtbo"]`
- **THEN** 构建系统将三个 `.dtbo` 文件纳入 kernel overlay 产物集合
- **AND** extlinux 配置仅引用 `i2c1.dtbo` 和 `display.dtbo`
- **AND** extlinux 配置中两个 overlay 的顺序与 `boot.default_overlays` 声明顺序一致

#### Scenario: 默认 overlay 引用未打包文件
- **WHEN** `boot.default_overlays` 包含 `missing.dtbo` 但 `boot.dtb_overlays` 不包含 `missing.dtbo`
- **THEN** boot 组件构建失败
- **AND** 错误信息包含缺失的 overlay 文件名

#### Scenario: 未声明 overlay 保持兼容
- **WHEN** `boot.dtb_overlays` 和 `boot.default_overlays` 均为空或未声明
- **THEN** kernel、boot 和 image 组件保持现有无 overlay 的构建行为
- **AND** extlinux 配置不生成 `fdtoverlays` 行

### Requirement: Kernel overlay 产物收集
支持 Device Tree Overlay 的平台 kernel builder 必须（SHALL）在 `boot.dtb_overlays` 非空时编译对应 `.dtbo`，并通过 collect 返回 `dtbos` 目录供构建引擎收集到 `target/kernel/overlay/`。当任一声明的 overlay 未生成时，kernel 构建必须（MUST）失败。

#### Scenario: overlay 编译成功
- **WHEN** `boot.dtb_overlays` 声明 `["i2c1.dtbo", "spi1.dtbo"]` 且内核源码提供对应 overlay 源文件和 Makefile 规则
- **THEN** `flange build kernel` 生成 `target/kernel/overlay/i2c1.dtbo`
- **AND** 生成 `target/kernel/overlay/spi1.dtbo`

#### Scenario: overlay 编译缺失
- **WHEN** `boot.dtb_overlays` 声明 `["i2c1.dtbo"]` 但内核构建后未产生 `i2c1.dtbo`
- **THEN** kernel 组件构建失败
- **AND** 错误信息包含 `i2c1.dtbo`

### Requirement: extlinux fdtoverlays 渲染
boot builder 必须（SHALL）把 `boot.default_overlays` 渲染为 extlinux 的 `fdtoverlays` 指令。该指令必须（MUST）支持多个 overlay 路径，并保持 `boot.default_overlays` 的声明顺序。

#### Scenario: Rockchip extlinux overlay 路径
- **WHEN** Rockchip target 的 `boot.default_overlays == ["i2c1.dtbo", "spi1.dtbo"]`
- **THEN** `/extlinux/extlinux.conf` 包含一行 `fdtoverlays /dtbs/rockchip/overlay/i2c1.dtbo /dtbs/rockchip/overlay/spi1.dtbo`

#### Scenario: Allwinner A733 extlinux overlay 路径
- **WHEN** Allwinner A733 target 的 `boot.default_overlays == ["i2c1.dtbo", "spi1.dtbo"]`
- **THEN** `/extlinux/extlinux.conf` 包含一行 `fdtoverlays /dtbs/allwinner/overlay/i2c1.dtbo /dtbs/allwinner/overlay/spi1.dtbo`

#### Scenario: 多 overlay 顺序保持
- **WHEN** `boot.default_overlays == ["first.dtbo", "second.dtbo", "third.dtbo"]`
- **THEN** extlinux 中 `fdtoverlays` 的路径顺序为 `first.dtbo`、`second.dtbo`、`third.dtbo`

### Requirement: boot 分区 overlay 文件布局
boot builder 必须（SHALL）将 `target/kernel/overlay/` 中被 `boot.dtb_overlays` 声明的 `.dtbo` 文件复制到平台约定的 boot 分区 overlay 目录。base DTB 必须（MUST）放在 `/dtbs/<vendor>/`，overlay 必须（MUST）放在 `/dtbs/<vendor>/overlay/`。生成 extlinux 前必须（MUST）校验 `boot.default_overlays` 引用的文件已存在于 staging 目录。

#### Scenario: Rockchip boot 分区包含 overlay
- **WHEN** Rockchip boot 组件构建且 `target/kernel/overlay/i2c1.dtbo` 存在
- **THEN** boot.img staging 中包含 `/dtbs/rockchip/overlay/i2c1.dtbo`

#### Scenario: Allwinner A733 boot 分区包含 overlay
- **WHEN** Allwinner A733 boot 组件构建且 `target/kernel/overlay/i2c1.dtbo` 存在
- **THEN** boot.img staging 中包含 `/dtbs/allwinner/overlay/i2c1.dtbo`

### Requirement: U-Boot overlay 加载地址
使用 extlinux `fdtoverlays` 的平台 U-Boot 环境必须（SHALL）定义 `fdtoverlay_addr_r`，且该地址不得（MUST NOT）与 kernel、FDT、script 或 ramdisk 加载地址重叠。

#### Scenario: U-Boot 环境包含 overlay 地址
- **WHEN** 构建应用 flange U-Boot patch 的 Rockchip 或 Allwinner A733 bootloader
- **THEN** U-Boot 默认环境中包含 `fdtoverlay_addr_r`

#### Scenario: extlinux 应用 overlay
- **WHEN** U-Boot sysboot 读取包含 `fdtoverlays` 的 extlinux 配置
- **THEN** U-Boot 使用 `fdtoverlay_addr_r` 加载并按顺序应用 overlay
- **AND** 成功后启动的 Linux 接收已合并 overlay 的 FDT
