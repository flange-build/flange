> **归档说明**：本变更方案属于 Bazel 构建系统时代（v1.0）。flange 已于 2026-04 迁移至 Python 统一架构（v2.0），本方案中涉及 Bazel/Starlark/BUILD.bazel 的实现细节仅作历史参考。

## Why

Phase 0-6 已完成从内核到镜像刷写的完整构建链路，但用户操作需要记住冗长的 `docker compose run --rm build bazel build //image --config=radxa-zero3w` 命令。需要一个 Android AOSP 风格的 CLI 脚手架，让用户 `source envsetup.sh && lunch && flange build` 即可完成所有操作。

## 非目标

- GUI 图形界面
- 构建系统本身的修改（Bazel rule、策略脚本等不变）
- 自动检测和安装 Docker/Docker Compose
- 远程构建或分布式构建支持

## What Changes

- **`envsetup.sh`**：source 到当前 shell，注入 `lunch` 和 `flange` 函数，设置环境变量
- **`lunch` 函数**：交互式板级选择菜单，自动扫描 `board/` 目录下的可用板子，选择后设置 `BOARD` 环境变量
- **`flange` 命令**：统一入口 shell 函数，分发到各子命令：
  - `flange build` — 在 Docker 容器内执行 `bazel build //image`
  - `flange kernel` — 单独构建内核
  - `flange bootloader` — 单独构建 bootloader
  - `flange rootfs` — 单独构建 rootfs
  - `flange flash` — 调用宿主机刷写脚本 `scripts/flange-flash.sh`
  - `flange collect` — 收集构建产物到 `target/<board>/`
  - `flange shell` — 进入 Docker 交互式 shell
  - `flange clean` — 清理构建产物
  - `flange status` — 显示当前板级配置和构建状态

## Capabilities

### New Capabilities
- `cli-envsetup`: envsetup.sh 环境初始化脚本，包含 lunch 板级选择和 flange 命令入口
- `cli-subcommands`: flange 各子命令的行为定义（build、kernel、flash、shell、clean、status 等）

### Modified Capabilities

（无需修改现有 spec）

## Impact

- **新增文件**: `envsetup.sh`（项目根目录）
- **无代码修改**: 所有现有构建规则和脚本不受影响，CLI 仅是封装层
- **依赖**: 要求宿主机已安装 Docker 和 Docker Compose