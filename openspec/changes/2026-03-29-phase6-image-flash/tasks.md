## 1. 构建环境准备

- [x] 1.1 Dockerfile 新增镜像打包工具（e2fsprogs、dosfstools、parted、kpartx）
- [x] 1.2 board/radxa-zero3w/board.bzl 新增 `boot` 配置块（dtb_overlays、default_overlays、kernel_args）

## 2. 内核构建扩展 — DTBO 收集

- [x] 2.1 kernel/rockchip/build.sh 新增 `KERNEL_DTBOS_DIR` 环境变量设置
- [x] 2.2 build/kernel_build.bzl 声明 `dtbos.tar.gz` 产出并增加收集逻辑
- [x] 2.3 build/kernel_collect.bzl 增加 dtbos.tar.gz 的解压处理

## 3. Boot 分区构建

- [x] 3.1 build/boot_partition.bzl 实现框架 rule（属性定义、环境变量设置、产物收集）
- [x] 3.2 image/rockchip/build_boot.sh 实现 Rockchip 平台 boot 分区策略脚本（目录组装、extlinux.conf 生成、mkfs.ext4 打包）

## 4. 镜像打包

- [x] 4.1 build/image_build.bzl 实现框架 rule（组件聚合、环境变量设置、产物收集）
- [x] 4.2 build/image_collect.bzl 实现产物收集 rule
- [x] 4.3 image/rockchip/parameter.txt 定义 Rockchip 默认分区布局
- [x] 4.4 image/rockchip/build_image.sh 实现 Rockchip 平台镜像打包策略脚本（分区表创建、dd bootloader、boot/rootfs 分区写入）

## 5. BUILD 文件与路由

- [x] 5.1 image/rockchip/BUILD.bazel 实例化 boot_partition + image_build + image_collect
- [x] 5.2 image/BUILD.bazel 实现顶层 alias + select() 路由（image + collect）

## 6. 刷写脚本

- [x] 6.1 scripts/flash/common.sh 实现通用工具函数（颜色输出、确认提示、设备检测）
- [x] 6.2 scripts/flash/rockchip.sh 实现 Rockchip 平台刷写逻辑（rkdeveloptool 调用）
- [x] 6.3 scripts/flange-flash.sh 实现主入口脚本（参数解析、平台分发、dd 刷写）

## 7. 构建验证

- [x] 7.1 在 Docker 容器内执行 `bazel build //image --config=radxa-zero3w`，验证产出 raw.img
- [x] 7.2 执行 `bazel run //image:collect --config=radxa-zero3w`，验证 target/ 目录产物完整
- [x] 7.3 验证 raw.img 分区表正确（fdisk -l 检查分区布局）
- [x] 7.4 验证 boot.img 内容正确（mount 检查 Image、DTB、extlinux.conf）
