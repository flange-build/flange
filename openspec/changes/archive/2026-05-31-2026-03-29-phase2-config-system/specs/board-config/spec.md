## ADDED Requirements

### Requirement: 板级配置文件声明完整构建参数
`board/radxa-zero3w/board.bzl` SHALL 导出板级配置 dict，包含该板子的完整构建参数，至少包括：`board`（板子名称）、`soc`（SoC 型号）、`platform`（所属平台）、`dts`（设备树名称）。

#### Scenario: 板级配置包含核心字段
- **WHEN** 查看 `board/radxa-zero3w/board.bzl` 导出的配置 dict
- **THEN** 包含 `board`、`soc`、`platform`、`dts` 字段

#### Scenario: 板级配置包含内核源码信息
- **WHEN** 查看板级配置的 `kernel` 字段
- **THEN** 包含 `repo`（仓库地址）和 `branch`（分支名）

#### Scenario: 板级配置包含 bootloader 源码信息
- **WHEN** 查看板级配置的 `bootloader` 字段
- **THEN** 包含 `repo`（仓库地址）和 `branch`（分支名）

### Requirement: 板级 BUILD.bazel 声明 filegroup
`board/radxa-zero3w/BUILD.bazel` SHALL 声明板级资源的 `filegroup`（如补丁、overlay），供组件构建规则通过 `deps` 引用。初始阶段可为空 filegroup。

#### Scenario: BUILD.bazel 包含 filegroup 声明
- **WHEN** 查看 `board/radxa-zero3w/BUILD.bazel`
- **THEN** 存在 `filegroup` target 声明

### Requirement: 板级配置声明 rootfs 基线版本
板级配置 dict SHALL 包含 `rootfs` 字段，声明根文件系统的基线版本（如 Ubuntu 代号）。

#### Scenario: radxa-zero3w 使用 noble 基线
- **WHEN** 查看 `board/radxa-zero3w/board.bzl` 中的 `rootfs` 配置
- **THEN** 包含 `"base": "noble"`
