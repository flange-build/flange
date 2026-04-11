> **归档说明**：本变更方案属于 Bazel 构建系统时代（v1.0）。flange 已于 2026-04 迁移至 Python 统一架构（v2.0），本方案中涉及 Bazel/Starlark/BUILD.bazel 的实现细节仅作历史参考。

## Why

Phase 0 已搭建 Docker 构建环境并在容器内安装了 aarch64-linux-gnu 交叉编译器，但 Bazel 尚不知道如何使用它。需要注册 Bazel CC toolchain 和 platform，使 `bazel build --platforms=//toolchain:aarch64_linux` 能产出 aarch64 二进制文件。这是内核、bootloader、rootfs 等所有组件构建的前提。

## What Changes

- 新增 `toolchain/BUILD.bazel`：定义 `cc_toolchain` 和 `toolchain`，声明 aarch64-linux-gnu 工具路径和 exec/target 约束
- 新增 `toolchain/cc_toolchain_config.bzl`：使用 `cc_common.create_cc_toolchain_config_info` 配置工具链细节（编译器路径、include 目录、链接器标志等）
- 新增 `toolchain/BUILD.bazel` 中的 `platform()` 定义：声明 aarch64 linux 目标平台
- 修改 `MODULE.bazel`：添加 `register_toolchains("//toolchain:aarch64_linux_toolchain")`
- 修改 `.bazelrc`：添加便捷 config（`--config=aarch64` 映射到 `--platforms`）

## 非目标

- 不支持 aarch64 以外的其他目标架构（如 armhf、riscv64）
- 不实现配置体系（registry.bzl、deep_merge），`--config=aarch64` 仅作为 `.bazelrc` 的快捷方式
- 不构建任何实际组件（kernel、bootloader 等）

## Capabilities

### New Capabilities
- `cross-compile-toolchain`：Bazel CC 交叉编译工具链注册，支持 aarch64-linux-gnu 目标

### Modified Capabilities

（无）

## Impact

- 修改文件：`MODULE.bazel`、`.bazelrc`
- 新增目录：`toolchain/`（`BUILD.bazel` + `cc_toolchain_config.bzl`）
- 验证标准：在容器内编译一个简单 C 程序，`file` 命令确认产出为 aarch64 ELF