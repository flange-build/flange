## Why

flange 的组件构建规则（kernel、bootloader、image）需要通过 `select()` 路由到正确的平台子目录，但目前缺少支撑这一路由的配置体系。没有配置体系，后续阶段的内核构建、U-Boot 构建都无法根据目标平台/板子自动选择正确的源码仓库、defconfig、补丁集等参数。

## What Changes

- 新增 `build/deep_merge.bzl`：提供 Starlark dict 深度合并工具函数，支撑三层配置继承
- 新增 `build/config_registry.bzl`：配置注册表，管理平台 → SoC → 板级三层配置的合并与查询
- 新增 `platform/rockchip/` 目录：Rockchip 平台级配置声明（通用参数）
- 新增 `platform/rockchip/rk3566/` 目录：RK3566 SoC 级配置声明
- 新增 `board/radxa-zero3w/` 目录：Radxa Zero 3W 板级配置声明
- 新增 Bazel `config_setting` 规则：支持 `select()` 路由到正确的平台组件实现
- 更新 `.bazelrc`：添加 `--config=radxa-zero3w` 快捷配置

## 非目标

- 本阶段不实现实际的组件构建规则（kernel/bootloader/rootfs/image），仅搭建配置体系骨架
- 不实现刷写逻辑
- 不添加 Rockchip 以外的平台配置

## Capabilities

### New Capabilities
- `config-deep-merge`：Starlark 深度合并工具，支撑三层配置继承
- `config-registry`：配置注册表，管理平台/SoC/板级配置的注册、合并与查询
- `platform-rockchip-config`：Rockchip 平台配置声明（含 RK3566 SoC 级配置）
- `board-config`：板级配置体系（以 radxa-zero3w 为首个实例）
- `bazel-config-routing`：Bazel config_setting 与 select() 路由机制

### Modified Capabilities
- `cross-compile-toolchain`：在 `.bazelrc` 中新增 `--config=radxa-zero3w` 配置，引用已有的 aarch64 platform

## Impact

- 新增 `build/`、`platform/`、`board/` 目录结构
- `.bazelrc` 新增板级配置项
- 为后续阶段（kernel、bootloader、rootfs、image）提供配置基础设施
- 所有后续组件构建规则将依赖本阶段的配置注册表获取参数
