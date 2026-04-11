> **归档说明**：本变更方案属于 Bazel 构建系统时代（v1.0）。flange 已于 2026-04 迁移至 Python 统一架构（v2.0），本方案中涉及 Bazel/Starlark/BUILD.bazel 的实现细节仅作历史参考。

## Why

flange 的 App 工程体系（`docs/app-architecture.md`）要求所有 App 通过 `flange_deb` 规则打包为 .deb 并安装到 rootfs。当前 `flange_deb` 规则尚未实现，`build/defs.bzl` 不存在，导致 `app/adbd` 等已就绪的 App 无法构建。

同时，现有 `rootfs_customize` 规则只支持从 `packages/` 目录读取预置 .deb，无法消费 Bazel 构建产出的 .deb（因为 Bazel 产出在 `bazel-bin/` 中，不能写入源码目录）。需要打通 "App 源文件 → .deb → rootfs" 的完整链路。

## What Changes

- **新增 `build/deb.bzl`**：实现 `flange_deb` Bazel 规则，将二进制/脚本/配置/资源/systemd unit 按路径映射打包为 .deb 格式
- **新增 `build/defs.bzl`**：统一导出入口，暴露 `flange_deb` 供 App 的 BUILD.bazel 加载
- **修改 `rootfs_customize`**：新增 `custom_deb_targets` 属性，接受 Bazel 构建的 .deb target 列表，与现有 `custom_packages_dir` 机制并存
- **修改 `rootfs/rockchip/BUILD.bazel`**：将 `app/adbd:adbd-deb` 加入 rootfs 的 deb targets
- **修改 `rootfs/rockchip/build_customize.sh`**：支持从环境变量接收 Bazel 产出的 .deb 路径并安装

## 非目标

- 不实现 `flange_cmake` / `flange_meson` / `flange_make` / `flange_swift` 等构建系统包装规则（后续独立实现）
- 不实现从 `app.yaml` 自动提取元数据（Starlark 无法解析 YAML，元数据在 BUILD.bazel 中声明，见 `docs/app-architecture.md` 11.1 节）
- 不处理 lib 类型的双包产出（libfoo + libfoo-dev），MVP 阶段专注 exec/service 类型
- 不添加 `rules_pkg` 外部依赖——使用 shell 脚本在 action 中直接构建 .deb（`ar` + `tar`），减少依赖

## Capabilities

### New Capabilities

- `flange-deb-rule`: `flange_deb` Bazel 规则实现，支持二进制/脚本/配置/资源的路径映射打包、conffiles 声明、systemd unit 安装与 auto_start、deb control 文件生成
- `deb-rootfs-integration`: Bazel 构建的 .deb 产物与 rootfs_customize 的集成通道，从 label target 到 rootfs 安装的完整链路

### Modified Capabilities

（无需修改现有 spec）

## Impact

- **新增文件**: `build/defs.bzl`、`build/deb.bzl`
- **修改文件**: `build/rootfs_customize.bzl`、`rootfs/rockchip/BUILD.bazel`、`rootfs/rockchip/build_customize.sh`
- **依赖**: 构建环境需要 `ar`、`tar`、`gzip` 命令（Docker 容器中通常自带）
- **消费者**: `app/adbd/BUILD.bazel` 是第一个使用 `flange_deb` 的 App，可作为端到端验证