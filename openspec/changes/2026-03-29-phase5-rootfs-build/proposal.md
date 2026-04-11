> **归档说明**：本变更方案属于 Bazel 构建系统时代（v1.0）。flange 已于 2026-04 迁移至 Python 统一架构（v2.0），本方案中涉及 Bazel/Starlark/BUILD.bazel 的实现细节仅作历史参考。

## Why

Phase 3/4 完成了内核和 bootloader 的构建，但系统启动后没有可用的根文件系统。Rootfs 是嵌入式系统的核心组件 — 没有它，内核和 bootloader 只是裸机固件。本阶段基于 ubuntu-base tarball 构建根文件系统，支持 apt 包安装和自定义 deb 包安装，产出 `rootfs.tar.gz`，为后续 Phase 6 镜像打包提供输入。

## What Changes

- 新增 `build/rootfs_build.bzl` 框架 rule，沿用框架+策略脚本架构
- 新增 `build/rootfs_source.bzl` repository rule，通过 HTTP 下载 ubuntu-base tarball
- 新增 `rootfs/` 组件目录，按平台分子目录（同 kernel/bootloader 模式）
- 新增 `rootfs/rockchip/build.sh` Rockchip 平台 rootfs 构建脚本
- 新增 `packages/` 目录结构，支持自定义 deb 包的组织和选择性安装
- 扩展 `build/extensions.bzl`，新增 `rootfs_sources` module extension
- 扩展 `board/radxa-zero3w/board.bzl`，补充 rootfs 完整配置（URL、包列表、自定义包）
- 修改 `docker/Dockerfile`，安装 `qemu-user-static` 支持跨架构 chroot

## 非目标

- 不生成 ext4 镜像 — 本阶段产出 `rootfs.tar.gz`，ext4 打包留给 Phase 6
- 不实现 hook 机制（pre/post build hooks）— 后续单独设计
- 不支持多架构同时构建 — 当前仅 arm64

## Capabilities

### New Capabilities
- `rootfs-build-rule`: rootfs_build 框架 rule 的环境变量契约、输入输出定义和构建流程
- `rootfs-rockchip`: Rockchip 平台 rootfs 构建脚本（qemu chroot + apt + overlay + 自定义 deb）
- `rootfs-select-routing`: rootfs 顶层 alias + select() 路由和产物收集
- `custom-packages`: 自定义 deb 包的目录结构、filegroup 导出和选择性安装机制

### Modified Capabilities
- `component-platform-layout`: rootfs 改为按平台分子目录（原规范要求扁平结构）
- `board-config`: board.bzl 扩展 rootfs 配置（完整 URL、sha256、包列表、自定义包列表）
- `docker-build-env`: Dockerfile 新增 qemu-user-static 依赖

## Impact

- **新增文件**: `build/rootfs_build.bzl`, `build/rootfs_source.bzl`, `rootfs/BUILD.bazel`, `rootfs/rockchip/BUILD.bazel`, `rootfs/rockchip/build.sh`, `packages/` 目录
- **修改文件**: `MODULE.bazel`, `build/extensions.bzl`, `board/radxa-zero3w/board.bzl`, `docker/Dockerfile`
- **Docker 镜像**: 需重新构建以包含 qemu-user-static
- **构建依赖**: 宿主机需注册 binfmt_misc（`docker run --privileged multiarch/qemu-user-static --reset`）
- **权限要求**: rootfs 构建需要 root 权限（chroot、mount），Bazel 使用 no-sandbox 执行