# image-rockchip Specification

## Purpose
TBD - created by archiving change 2026-03-29-phase6-image-flash. Update Purpose after archive.
## Requirements
### Requirement: Rockchip 平台 boot 分区构建脚本
`image/rockchip/build_boot.sh` SHALL 实现 Rockchip 平台的 boot 分区构建流程：创建目录结构 → 复制 Image 和 DTB → 解压 DTBO → 生成 extlinux.conf → mkfs.ext4 打包为 boot.img。

#### Scenario: boot 分区目录结构
- **WHEN** build_boot.sh 组装 boot 分区内容
- **THEN** 创建 `/Image`、`/dtb/rockchip/<dts>.dtb`、`/extlinux/extlinux.conf` 结构

#### Scenario: extlinux.conf 内容正确
- **WHEN** `BOOT_DEFAULT_OVERLAYS` 包含 overlay 列表且 `BOOT_KERNEL_ARGS` 包含内核参数
- **THEN** 生成的 extlinux.conf 包含正确的 `kernel`、`fdt`、`fdtoverlays`（如有）、`append` 行

#### Scenario: DTBO 文件解压
- **WHEN** `BOOT_DTBOS_DIR` 非空且包含 .dtbo 文件
- **THEN** DTBO 文件被复制到 boot 分区的 `/dtb/rockchip/overlay/` 目录

### Requirement: Rockchip 平台镜像打包脚本
`image/rockchip/build_image.sh` SHALL 实现 Rockchip 平台的磁盘镜像打包流程：解析 parameter.txt → 创建空白镜像 → 写入分区表 → dd bootloader 到对应偏移 → 写入 boot 和 rootfs 分区 → 产出 raw.img。

#### Scenario: 完整打包流程
- **WHEN** image_build 框架调用 `image/rockchip/build_image.sh`
- **THEN** 产出的 raw.img 包含完整的分区表、bootloader、boot 分区和 rootfs 分区

#### Scenario: bootloader 写入正确偏移
- **WHEN** parameter.txt 定义 uboot 分区偏移为 0x4000 扇区
- **THEN** u-boot.itb 被 dd 到 raw.img 的对应偏移位置

#### Scenario: rootfs 从 tar.gz 转 ext4
- **WHEN** 打包脚本处理 rootfs
- **THEN** 创建 ext4 文件系统，将 rootfs.tar.gz 解压到其中，生成 UUID 并回写到 extlinux.conf

### Requirement: Rockchip parameter.txt 分区定义
`image/rockchip/parameter.txt` SHALL 定义 Rockchip 平台的默认分区布局，包含 uboot、misc、boot、rootfs 分区的偏移和大小。

#### Scenario: 默认分区布局
- **WHEN** 查看 `image/rockchip/parameter.txt`
- **THEN** 包含 `CMDLINE` 行定义至少 uboot、boot、rootfs 分区的偏移和大小

#### Scenario: 分区类型为 GPT
- **WHEN** 查看 parameter.txt 的 TYPE 字段
- **THEN** 值为 `GPT`

### Requirement: Rockchip 镜像 BUILD.bazel 实例化
`image/rockchip/BUILD.bazel` SHALL 实例化 `boot_partition` 和 `image_build` rule，通过 `select()` 按板级配置传入参数。

#### Scenario: radxa-zero3w 构建参数
- **WHEN** 使用 `--config=radxa-zero3w` 构建
- **THEN** boot_partition 使用 `//kernel/rockchip` 的产物、board.bzl 中的 boot 配置；image_build 聚合 boot + bootloader + rootfs 产物

### Requirement: Rockchip 镜像产物收集
`image/rockchip/BUILD.bazel` SHALL 包含 `image_collect` 实例，收集 raw.img 和各组件镜像到 `target/<board>/image/` 目录，同时复制 parameter.txt 供刷写脚本使用。

#### Scenario: 收集产物完整
- **WHEN** 执行 `bazel run //image:collect --config=radxa-zero3w`
- **THEN** `target/radxa-zero3w/image/` 包含 `raw.img`、`idbloader.img`、`u-boot.itb`、`boot.img`、`rootfs.tar.gz`、`parameter.txt`

