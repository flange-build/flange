## Why

Phase 0-5 已完成内核、Bootloader、Rootfs 三大组件的独立构建，但产物分散为 Image、DTB、idbloader.img、u-boot.itb、rootfs.tar.gz 等文件，无法直接刷入设备。用户需要一个端到端的流程：`bazel build //image` 产出完整刷写镜像，然后在宿主机执行刷写脚本将镜像写入目标设备。

此外，当前内核构建未收集 DTB overlay（.dtbo）文件，无法支持硬件外设的动态启用。

## 非目标

- 设备上动态修改 DTB overlay（编辑 extlinux.conf 后不重新构建）——后续支持
- OTA/增量更新机制
- 多存储介质支持（UFS、SPI）——本阶段仅覆盖 SD/eMMC
- CI/CD 自动刷写流水线

## What Changes

- **内核构建扩展**：`kernel_build.bzl` 和平台策略脚本增加 DTBO 收集，打包为 `dtbos.tar.gz`
- **boot 分区构建**：新增 `boot_partition.bzl` 框架 rule，将 Image + DTB + DTBO + extlinux.conf 组装为 ext4 boot.img
- **extlinux.conf 生成**：构建时根据 board 配置生成 extlinux.conf，使用 `fdtoverlays` 指令声明默认启用的 overlay
- **镜像打包**：新增 `image_build.bzl` 框架 rule，聚合 bootloader + boot.img + rootfs → raw.img 完整磁盘镜像
- **Rockchip 平台实现**：`image/rockchip/build.sh` 策略脚本按 parameter.txt 定义的分区表组装镜像
- **产物收集**：新增 `image_collect.bzl`，将完整镜像和各组件镜像收集到 `target/<board>/image/`
- **宿主机刷写脚本**：独立于 Bazel 的 shell 脚本，从 `target/<board>/image/` 读取产物，调用平台刷写工具（Rockchip: rkdeveloptool）执行整盘或组件级刷写
- **board 配置扩展**：`board.bzl` 新增 `boot` 配置块（dtb_overlays、default_overlays、kernel_args）

## Capabilities

### New Capabilities
- `boot-partition-rule`: boot 分区构建规则，将内核镜像、DTB、DTB overlay 和 extlinux.conf 组装为 ext4 boot.img
- `image-build-rule`: 镜像打包框架规则，聚合各组件分区镜像为完整磁盘镜像（raw.img）
- `image-rockchip`: Rockchip 平台镜像打包实现，包含 parameter.txt 分区定义和平台打包脚本
- `image-select-routing`: 镜像顶层 alias + select() 路由
- `flash-script`: 宿主机刷写脚本，支持整盘刷写和组件级刷写

### Modified Capabilities
- `board-config`: 新增 `boot` 配置块（dtb_overlays、default_overlays、kernel_args）
- `docker-build-env`: 构建容器新增 `e2fsprogs`（mkfs.ext4）、`dosfstools`（mkfs.vfat）、`parted`（分区表操作）等镜像打包工具

## Impact

- **新增目录**: `image/`、`image/rockchip/`、`scripts/`、`scripts/flash/`
- **新增构建规则**: `build/boot_partition.bzl`、`build/image_build.bzl`、`build/image_collect.bzl`
- **修改构建规则**: `build/kernel_build.bzl`（增加 dtbos.tar.gz 产出）
- **修改平台脚本**: `kernel/rockchip/build.sh`（增加 KERNEL_DTBOS_DIR）
- **修改配置**: `board/radxa-zero3w/board.bzl`（增加 boot 配置）、`docker/Dockerfile`（增加打包工具）
- **修改 BUILD 文件**: `kernel/rockchip/BUILD.bazel`（传递 dtb overlay 配置）
