## MODIFIED Requirements

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
