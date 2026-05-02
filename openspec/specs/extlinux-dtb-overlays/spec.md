# extlinux-dtb-overlays Specification

## Purpose
TBD - created by archiving change add-extlinux-dtb-overlays. Update Purpose after archive.
## Requirements
### Requirement: Device Tree Overlay 配置契约
平台、SoC、board 或 product 配置 MUST 通过 `boot.dtb_overlays` 声明需要从内核源码树（in-tree）构建并打包的 Device Tree Overlay 文件列表，MUST 通过 `boot.vendor_overlays` 声明需要从外部 vendor overlay 仓库构建并打包的 Device Tree Overlay 文件列表，MUST 通过 `boot.default_overlays` 声明默认启动时需要应用的 overlay 文件列表。

`boot.default_overlays` MUST 保持声明顺序，并 MUST 是 `boot.dtb_overlays ∪ boot.vendor_overlays`（按 basename）的子集。

`boot.dtb_overlays` 与 `boot.vendor_overlays` 的 basename MUST NOT 重复——撞名时构建 MUST 失败，错误信息 MUST 列出冲突项与各自来源。

每个字段的每一项 MUST 是非空字符串，MUST 以 `.dtbo` 结尾，MUST NOT 包含 `/`，MUST NOT 以 `.` 起头。

#### Scenario: 同时声明两源 overlay
- **WHEN** 最终配置中 `boot.dtb_overlays == ["my-local.dtbo"]`、`boot.vendor_overlays == ["radxa-zero3-external-antenna.dtbo", "rk3568-i2c1.dtbo"]` 且 `boot.default_overlays == ["rk3568-i2c1.dtbo"]`
- **THEN** 构建系统将 `my-local.dtbo` 通过 in-tree 流程构建，将 `radxa-zero3-external-antenna.dtbo`、`rk3568-i2c1.dtbo` 通过 vendor overlay 仓库流程构建
- **AND** 三个 `.dtbo` 文件全部纳入打包集合
- **AND** extlinux 配置仅引用 `rk3568-i2c1.dtbo`

#### Scenario: 默认 overlay 引用未打包文件
- **WHEN** `boot.default_overlays` 包含 `missing.dtbo` 但 `boot.dtb_overlays` 与 `boot.vendor_overlays` 的并集不包含 `missing.dtbo`
- **THEN** boot 组件构建失败
- **AND** 错误信息包含缺失的 overlay 文件名
- **AND** 错误信息列出 `boot.dtb_overlays` 与 `boot.vendor_overlays` 各自的候选集合

#### Scenario: 两源 basename 撞名
- **WHEN** `boot.dtb_overlays` 与 `boot.vendor_overlays` 同时包含 `foo.dtbo`
- **THEN** 构建失败
- **AND** 错误信息明确指出冲突的 basename `foo.dtbo` 同时来自两源

#### Scenario: 未声明 overlay 保持兼容
- **WHEN** `boot.dtb_overlays`、`boot.vendor_overlays` 与 `boot.default_overlays` 均为空或未声明
- **THEN** kernel、device-tree-overlay、boot 与 image 组件保持现有无 overlay 的构建行为
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
boot builder MUST 将 `target/kernel/overlay/` 中被 `boot.dtb_overlays` 声明的 `.dtbo` 文件，以及 device-tree-overlay 组件产物中被 `boot.vendor_overlays` 声明的 `.dtbo` 文件，复制到平台约定的 boot 分区 overlay 目录。

base DTB MUST 放在 `/dtbs/<vendor>/`，所有 overlay（无论来自哪一源）MUST 平铺在 `/dtbs/<vendor>/overlay/`，文件名即 basename。

复制阶段若发现 dst 中已存在同名 `.dtbo` 文件 → MUST raise 异常并终止构建。

生成 extlinux 前 MUST 校验 `boot.default_overlays` 引用的文件已存在于 staging 目录。

#### Scenario: Rockchip boot 分区两源平铺
- **WHEN** Rockchip boot 组件构建，`boot.dtb_overlays == ["my-local.dtbo"]` 且 `boot.vendor_overlays == ["rk3568-i2c1.dtbo"]`
- **THEN** boot.img staging 中包含 `/dtbs/rockchip/overlay/my-local.dtbo`
- **AND** boot.img staging 中包含 `/dtbs/rockchip/overlay/rk3568-i2c1.dtbo`

#### Scenario: Allwinner A733 boot 分区两源平铺
- **WHEN** Allwinner A733 boot 组件构建，`boot.dtb_overlays == ["my-local.dtbo"]` 且 `boot.vendor_overlays == ["a733-foo.dtbo"]`
- **THEN** boot.img staging 中包含 `/dtbs/allwinner/overlay/my-local.dtbo`
- **AND** boot.img staging 中包含 `/dtbs/allwinner/overlay/a733-foo.dtbo`

#### Scenario: dst 撞名报错
- **WHEN** in-tree 与 vendor 两源同时声明 `foo.dtbo`，复制时 dst 中已存在
- **THEN** 复制阶段 raise 异常
- **AND** 异常信息包含已存在路径与本次源路径，可定位冲突来源

### Requirement: vendor overlay 仓库构建
flange MUST 提供独立组件 `device-tree-overlay`，从外部 vendor overlay 仓库（git pin 到固定 ref）按 `boot.vendor_overlays` 列表编译 `.dtbo` 产物。

该组件 MUST vendor 无关，从 `config["vendor"]` 读取 vendor 名（如 `rockchip`、`allwinner`），用于在仓库中定位子目录 `arch/arm64/boot/dts/<vendor>/overlays/<stem>.{dts,dtso}`。源文件后缀 MUST 同时支持 `.dts`（rockchip 等子目录传统格式）与 `.dtso`（allwinner 等子目录在 kernel ≥ 6.2 引入的新格式）。`config["vendor"]` 字段缺失或值在仓库中无对应子目录时 MUST 报错并明确指出问题。

编译流程 MUST 等价于：

```bash
cpp -nostdinc -undef -x assembler-with-cpp -E \
    -I {kernel_src_dir}/include \
    -I {vendor_src_dir}/arch/arm64/boot/dts/{vendor}/overlays \
    {dts_or_dtso} -o {tmp}
dtc -@ -I dts -O dtb -o {dtbo} {tmp}
```

其中 `kernel_src_dir` 取自 kernel 组件的源码目录，`vendor_src_dir` 取自 device-tree-overlay 组件的源码目录。

`boot.vendor_overlays` 中声明的 stem 在仓库对应 vendor 子目录下不存在（`.dts` / `.dtso` 都没有）时 MUST 报错，错误信息 MUST 列出该 vendor 下若干可用 stem 与总数。

#### Scenario: 编译声明的 vendor overlay (.dts)
- **WHEN** `boot.vendor_overlays == ["radxa-zero3-external-antenna.dtbo"]` 且 `config["vendor"] == "rockchip"`，仓库中存在 `arch/arm64/boot/dts/rockchip/overlays/radxa-zero3-external-antenna.dts`
- **THEN** device-tree-overlay 组件成功编译并把 `radxa-zero3-external-antenna.dtbo` 收集到该组件 target 子目录

#### Scenario: 编译声明的 vendor overlay (.dtso)
- **WHEN** `boot.vendor_overlays == ["sun60iw2p1-spi1-spidev.dtbo"]` 且 `config["vendor"] == "allwinner"`，仓库中存在 `arch/arm64/boot/dts/allwinner/overlays/sun60iw2p1-spi1-spidev.dtso`
- **THEN** device-tree-overlay 组件成功编译并把 `sun60iw2p1-spi1-spidev.dtbo` 收集到该组件 target 子目录

#### Scenario: 仓库中找不到声明的 stem
- **WHEN** `boot.vendor_overlays == ["nonexistent-overlay.dtbo"]` 且仓库对应 vendor 子目录中既无 `nonexistent-overlay.dts` 也无 `nonexistent-overlay.dtso`
- **THEN** device-tree-overlay 组件构建失败
- **AND** 错误信息包含 `nonexistent-overlay`
- **AND** 错误信息列出该 vendor 下若干可用 stem 名与总数

#### Scenario: 缺失 config.vendor
- **WHEN** `boot.vendor_overlays` 非空但 `config` 顶层无 `vendor` 字段
- **THEN** device-tree-overlay 组件构建失败
- **AND** 错误信息明确指出 `vendor` 字段需补充

#### Scenario: 空 vendor_overlays short-circuit
- **WHEN** `boot.vendor_overlays == []`
- **THEN** device-tree-overlay 组件 source 阶段仍执行（保持内容哈希稳定）
- **AND** compile 阶段不执行任何 cpp / dtc 调用
- **AND** 该组件 target 子目录为空

### Requirement: vendor overlay 仓库 source pin
device-tree-overlay 组件的 source 声明 MUST pin 到外部 vendor overlay 仓库的固定 git ref（推荐 release tag）。flange 内容哈希 MUST 包含该 ref，使 ref 升级时整个组件链触发增量重 build。

#### Scenario: ref 变更触发重建
- **WHEN** `components/device-tree-overlay/config.py` 中的 git ref 从 `tagA` 改为 `tagB`
- **AND** 其他配置不变
- **THEN** device-tree-overlay 组件被识别为内容变化
- **AND** 触发该组件及下游 boot 组件的重建

### Requirement: U-Boot overlay 加载地址
使用 extlinux `fdtoverlays` 的平台 U-Boot 环境必须（SHALL）定义 `fdtoverlay_addr_r`，且该地址不得（MUST NOT）与 kernel、FDT、script 或 ramdisk 加载地址重叠。

#### Scenario: U-Boot 环境包含 overlay 地址
- **WHEN** 构建应用 flange U-Boot patch 的 Rockchip 或 Allwinner A733 bootloader
- **THEN** U-Boot 默认环境中包含 `fdtoverlay_addr_r`

#### Scenario: extlinux 应用 overlay
- **WHEN** U-Boot sysboot 读取包含 `fdtoverlays` 的 extlinux 配置
- **THEN** U-Boot 使用 `fdtoverlay_addr_r` 加载并按顺序应用 overlay
- **AND** 成功后启动的 Linux 接收已合并 overlay 的 FDT

