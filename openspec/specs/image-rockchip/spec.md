# image-rockchip Specification

## Purpose

定义 Rockchip 平台镜像侧的落地契约：boot 分区构建、镜像装配、parameter.txt 分区定义、产物收集，以及生成的分区表与 DTS 启动参数之间的交叉校验。

## Requirements
### Requirement: Rockchip 平台 boot 分区构建脚本

Rockchip boot 构建 SHALL 按 FINAL_CONFIG 的 boot format 路由。extlinux 模式 SHALL 保持现有
流程：创建目录结构、复制 Image/DTB/DTBO、生成 extlinux.conf 并打包 ext4 `boot.img`。
vendor FIT 模式 SHALL 使用内核提供的 FIT 生成器把配置声明的 kernel payload、DTB 与 resource
打包为 `boot.img`，不得额外创建 extlinux 或 ext4 文件系统。

#### Scenario: boot 分区目录结构
- **WHEN** extlinux 模式组装 boot 分区内容
- **THEN** 创建 `/Image`、`/dtb/rockchip/<dts>.dtb`、`/extlinux/extlinux.conf` 结构

#### Scenario: extlinux.conf 内容正确
- **WHEN** extlinux 模式的 `BOOT_DEFAULT_OVERLAYS` 包含 overlay 列表且
  `BOOT_KERNEL_ARGS` 包含内核参数
- **THEN** 生成的 extlinux.conf 包含正确的 `kernel`、`fdt`、`fdtoverlays`（如有）、
  `append` 行

#### Scenario: DTBO 文件解压
- **WHEN** extlinux 模式的 `BOOT_DTBOS_DIR` 非空且包含 `.dtbo` 文件
- **THEN** DTBO 文件被复制到 boot 分区的 `/dtb/rockchip/overlay/` 目录

#### Scenario: vendor FIT 模式不生成 extlinux
- **WHEN** `kernel.boot_format=fit`
- **THEN** `boot.img` 是包含目标 kernel 与 FDT 的 FIT
- **AND** 构建过程不调用 `mke2fs` 且不生成 extlinux.conf

### Requirement: Rockchip 平台镜像打包脚本

Rockchip image 构建 SHALL 按 FINAL_CONFIG 和物理存储能力选择映射。非 SPI NAND 的 `gpt` 模式
SHALL 创建磁盘 `raw.img` 并写入 GPT/bootloader/boot/rootfs；`storage.type=spinand` 时无论
`partitions.format` 为 GPT 或 MTD，构建系统都 SHALL 从最终 entries/parameter 生成
`parameter.txt` 与具名刷写 manifest，不得生成整片 `raw.img`。

#### Scenario: 完整 GPT 打包流程
- **WHEN** image builder 处理 `partitions.format=gpt`
- **THEN** 产出的 `raw.img` 包含完整分区表、bootloader、boot 与 rootfs 分区

#### Scenario: bootloader 写入正确偏移
- **WHEN** GPT parameter 定义 uboot 分区偏移为 `0x4000` 扇区
- **THEN** `u-boot.itb` 被写到 `raw.img` 的对应偏移位置

#### Scenario: rootfs 从 staging 转 ext4
- **WHEN** GPT/ext4 路径处理 rootfs
- **THEN** 创建 ext4 文件系统、生成 UUID 并让 extlinux 引用正确 rootfs

#### Scenario: GPT/SPI NAND 使用 UBI 具名产物
- **WHEN** GPT image builder 处理 `storage.type=spinand` 与 `rootfs.image_format=ubi`
- **THEN** manifest 将 rootfs 分区映射到 `rootfs.ubi`
- **AND** 不查找 `rootfs.img` 或生成 `raw.img`

### Requirement: Rockchip parameter.txt 分区定义
`image/rockchip/parameter.txt` SHALL 定义 Rockchip 平台的默认分区布局，包含 uboot、misc、boot、rootfs 分区的偏移和大小。

#### Scenario: 默认分区布局
- **WHEN** 查看 `image/rockchip/parameter.txt`
- **THEN** 包含 `CMDLINE` 行定义至少 uboot、boot、rootfs 分区的偏移和大小

#### Scenario: 分区类型为 GPT
- **WHEN** 查看 parameter.txt 的 TYPE 字段
- **THEN** 值为 `GPT`

### Requirement: Rockchip 镜像装配由平台工厂实例化

`builder/platforms/rockchip/__init__.py` 的 `create_builder` SHALL 按组件名
返回对应的 Rockchip 构建器；镜像装配 SHALL 由 `RockchipImageBuilder` 承担，
它继承公共的 `GptImageBuilder`，只覆写平台声明位（见 `image-build-rule`）。

平台选择由配置的 `platform` 字段驱动，不需要在框架层维护条件分支。

#### Scenario: 按组件名返回构建器
- **WHEN** engine 为 rockchip 平台请求 `image` 组件的构建器
- **THEN** 返回 `RockchipImageBuilder` 实例

#### Scenario: 装配聚合上游产物
- **WHEN** 构建 rockchip 的 image 组件
- **THEN** 从当前 target 目录读取 bootloader、boot、rootfs（以及启用时的
  recovery）产物，按分区表装配进 raw.img

### Requirement: Rockchip 镜像产物收集

Rockchip image 收集 SHALL 根据最终构建路由复制必需产物。块设备 GPT/ext4 路径 SHALL 保持
收集 `raw.img`、bootloader、boot、rootfs 与 parameter；GPT/UBI SPI NAND 路径 SHALL 收集
loader、idbloader、U-Boot、FIT boot、AMP、UBI rootfs、生成的 parameter、具名刷写 manifest
和 flash config。

#### Scenario: GPT 产物收集保持完整
- **WHEN** 收集现有 Rockchip GPT/ext4 target
- **THEN** 目标目录仍包含 `raw.img`、bootloader、`boot.img`、`rootfs.img` 与
  `parameter.txt`

#### Scenario: SPI NAND GPT/UBI 产物收集完整
- **WHEN** 收集 RK3506B SPI NAND target
- **THEN** 目标目录包含 loader、`boot.img`、`amp.img`、`rootfs.ubi`、
  `parameter.txt`、`mtd-bundle.json` 和 `flash-config.json`
- **AND** flash config 声明具名 DI 路由而非整片 raw 写入

### Requirement: 生成的 parameter 与 DTS 启动参数交叉校验

当 target 使用 `ubi.mtd=<index>` 时，image/flash config SHALL 解析从最终 GPT entries 生成的
`parameter.txt`，确认对应 index 的分区名为 rootfs，并确认所有分区末端不超过配置声明的存储容量。
该校验 SHALL 由 `storage.type=spinand && rootfs.image_format=ubi` 触发，不得依赖
`partitions.format` 的字符串取值。

#### Scenario: rootfs MTD index 匹配
- **WHEN** DTS 声明 `ubi.mtd=5` 且 parameter 的第六个分区为 rootfs
- **THEN** 生成布局校验通过

#### Scenario: rootfs MTD index 错误
- **WHEN** DTS 声明 `ubi.mtd=5` 但 parameter 的第六个分区不是 rootfs
- **THEN** image 构建失败并报告 index、实际名称与期望名称

