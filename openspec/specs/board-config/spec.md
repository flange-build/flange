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

#### Scenario: 板级配置包含 boot 引导参数
- **WHEN** 查看板级配置的 `boot` 字段
- **THEN** 包含 `kernel_args`（内核启动参数）、`dtb_overlays`（打包的 dtbo 列表）、`default_overlays`（默认启用的 overlay 列表）

### Requirement: 板级 BUILD.bazel 声明 filegroup
`board/radxa-zero3w/BUILD.bazel` SHALL 声明板级资源的 `filegroup`（如补丁、overlay），供组件构建规则通过 `deps` 引用。初始阶段可为空 filegroup。

#### Scenario: BUILD.bazel 包含 filegroup 声明
- **WHEN** 查看 `board/radxa-zero3w/BUILD.bazel`
- **THEN** 存在 `filegroup` target 声明

### Requirement: 板级配置声明 rootfs 基线版本
板级配置 dict SHALL 包含 `rootfs` 字段，声明根文件系统的完整构建参数：`url`（ubuntu-base tarball 完整下载地址）、`packages`（apt 包列表）、`custom_packages`（自定义 deb 包组件名列表，可选）。`sha256` 为可选字段，用于 tarball 完整性校验。

#### Scenario: radxa-zero3w rootfs 配置
- **WHEN** 查看 `board/radxa-zero3w/board.bzl` 中的 `rootfs` 配置
- **THEN** 包含 `url`（ubuntu-base tarball 地址）、`packages`（apt 包名列表）

#### Scenario: 自定义包配置
- **WHEN** 板子需要安装自定义 deb 包
- **THEN** `rootfs.custom_packages` 列表中包含对应的组件目录名（如 `["gpu-driver"]`）

#### Scenario: sha256 可选
- **WHEN** 板级配置未声明 `rootfs.sha256`
- **THEN** 构建仍可正常执行（但建议提供以确保可重复构建）
