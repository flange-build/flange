> **归档说明**：本变更方案属于 Bazel 构建系统时代（v1.0）。flange 已于 2026-04 迁移至 Python 统一架构（v2.0），本方案中涉及 Bazel/Starlark/BUILD.bazel 的实现细节仅作历史参考。

## Why

当前 rootfs 构建将所有输入（ubuntu-base tarball、apt 包列表、自定义 deb、overlay）耦合在同一个 Bazel action 中。任何输入变化（即使只改了 overlay 文件）都触发完整重建（~38 分钟），其中 apt-get update + install 通过 qemu 模拟执行是主要瓶颈。参考 Armbian 的多层缓存架构，核心优化思路是：按变化频率拆分 Bazel rule，让慢变输入（包列表）和快变输入（overlay、自定义 deb）各自独立缓存。

## What Changes

- **拆分 `rootfs_build` 为两个 rule**：`rootfs_base`（tarball + apt 包 → base-rootfs.tar.zst）和 `rootfs_customize`（base + custom debs + overlay → rootfs.tar.gz），改 overlay 只重跑 customize 步骤（~1-2 分钟）
- **新增 APT 下载缓存**：Docker volume 持久化 apt .deb 下载缓存，即使 `rootfs_base` cache miss 也不用重新下载包
- **切换压缩算法为 zstd**：base rootfs 产物使用 zstdmt 多线程压缩，替代 gzip，压缩/解压速度提升 3-5x
- **拆分平台构建脚本**：`build.sh` 拆为 `build_base.sh`（chroot + apt install）和 `build_customize.sh`（custom debs + overlay + 打包）
- Dockerfile 新增 `zstd` 包

## 非目标

- 不实现 Armbian 的月度缓存轮换机制 — Bazel 的 input hash 已提供更精确的缓存失效
- 不实现 OCI 远程缓存 — 当前为单机构建场景
- 不实现 apt-cacher-ng 代理 — APT 下载缓存已足够
- 不改变 rootfs 的对外接口 — `bazel build //rootfs --config=radxa-zero3w` 命令不变，最终产物仍为 `rootfs.tar.gz`

## Capabilities

### New Capabilities
- `rootfs-base-rule`: rootfs_base Bazel rule，负责 ubuntu-base + apt 包安装，产出 base-rootfs.tar.zst
- `rootfs-customize-rule`: rootfs_customize Bazel rule，负责自定义 deb 安装 + overlay 应用，产出 rootfs.tar.gz
- `apt-cache-persistence`: Docker volume 持久化 APT 下载缓存机制

### Modified Capabilities
- `rootfs-build-rule`: 原 rootfs_build 规则拆分为 rootfs_base + rootfs_customize，原 rule 移除
- `rootfs-rockchip`: 平台构建脚本拆分为 build_base.sh 和 build_customize.sh
- `rootfs-select-routing`: 顶层 alias 路由目标从单一 rule 改为 customize rule
- `docker-build-env`: 新增 zstd 包和 APT 缓存 volume

## Impact

- **构建规则**：`build/rootfs_build.bzl` 拆分为 `build/rootfs_base.bzl` + `build/rootfs_customize.bzl`，原文件移除
- **平台脚本**：`rootfs/rockchip/build.sh` 拆分为 `build_base.sh` + `build_customize.sh`
- **BUILD.bazel**：`rootfs/rockchip/BUILD.bazel` 改为实例化两个 rule
- **Docker 环境**：Dockerfile 加 `zstd`，docker-compose.yml 加 APT 缓存 volume
- **产物收集**：`rootfs_collect` 不变，仍从 customize rule 的 rootfs.tar.gz 收集
- **用户命令**：`bazel build //rootfs --config=radxa-zero3w` 不变