### Requirement: 组件目录按平台分子目录
差异度高的组件目录（kernel、bootloader、image）SHALL 按平台建立子目录，每个子目录包含独立的 `BUILD.bazel` 和平台特有的构建脚本、补丁文件。rootfs 目录 SHALL 保持扁平结构。

#### Scenario: kernel 目录包含平台子目录
- **WHEN** 查看 kernel/ 目录结构
- **THEN** 存在 rockchip/、allwinner/、qualcomm/ 等平台子目录，每个子目录包含 `BUILD.bazel`

#### Scenario: rootfs 目录保持扁平
- **WHEN** 查看 rootfs/ 目录结构
- **THEN** 只有一个顶层 `BUILD.bazel`，不存在平台子目录

### Requirement: bootloader 目录取代 uboot 目录
项目 SHALL 使用 `bootloader/` 作为引导加载程序的组件目录名，取代原有的 `uboot/`。该目录下按平台建子目录，可容纳 U-Boot、ABL/XBL 等不同 bootloader 实现。

#### Scenario: Rockchip 平台使用 U-Boot
- **WHEN** 查看 bootloader/rockchip/ 目录
- **THEN** 包含 U-Boot 相关的构建逻辑（TPL+SPL → idbloader, ATF+u-boot → u-boot.itb）

#### Scenario: Qualcomm 平台使用 ABL
- **WHEN** 查看 bootloader/qualcomm/ 目录
- **THEN** 包含 ABL/XBL 相关的构建逻辑，而非 U-Boot

### Requirement: 组件目录遵循顶层 alias + select() 路由模式
每个嵌入式组件（kernel、bootloader 等）SHALL 在顶层目录提供 alias target，通过 `select()` 按平台 `config_setting` 路由到 `<component>/<platform>/` 子目录的具体实现。每个平台子目录包含 `BUILD.bazel`（规则实例化）和 `build.sh`（平台策略脚本）。

#### Scenario: kernel 组件遵循此模式
- **WHEN** 查看 `kernel/BUILD.bazel`
- **THEN** 包含 alias 通过 `select()` 路由到 `//kernel/rockchip`

#### Scenario: bootloader 组件遵循此模式
- **WHEN** 查看 `bootloader/BUILD.bazel`
- **THEN** 包含 alias 通过 `select()` 路由到 `//bootloader/rockchip`

#### Scenario: 新增平台只需在顶层加一行
- **WHEN** 需要新增 Amlogic 平台的 kernel 支持
- **THEN** 只需在 `kernel/BUILD.bazel` 的 `select()` 中增加一行 `"//config:amlogic": "//kernel/amlogic"`

### Requirement: 板级资源通过 filegroup 导出
板级补丁、DTS 等数据文件 SHALL 存放在 `board/<name>/patches/` 目录下，由 `board/<name>/BUILD.bazel` 通过 `filegroup` 导出，组件构建规则通过 `deps` 引用。

#### Scenario: 板级内核补丁通过 filegroup 提供
- **WHEN** rk3588-evb 板子有特有的内核补丁
- **THEN** 补丁文件位于 `board/rk3588-evb/patches/kernel/`，由 `board/rk3588-evb/BUILD.bazel` 导出名为 `kernel_patches` 的 `filegroup`

#### Scenario: 组件构建规则引用板级补丁
- **WHEN** `kernel/rockchip/BUILD.bazel` 需要应用板级补丁
- **THEN** 通过 `deps` 或 `srcs` 引用 `//board/<name>:kernel_patches` filegroup

### Requirement: platform 目录为纯配置声明
`platform/` 目录 SHALL 只包含配置值声明（repo URL、defconfig 名、工具链、包列表等），MUST NOT 存放补丁文件、构建脚本等数据资源。

#### Scenario: platform 目录不包含补丁文件
- **WHEN** 查看 `platform/rockchip/` 目录
- **THEN** 只有 `.bzl` 配置文件，不存在 `patches/`、`scripts/` 等数据目录

#### Scenario: 平台通用补丁存放在组件目录
- **WHEN** Rockchip 平台有通用的内核补丁
- **THEN** 补丁文件位于 `kernel/rockchip/patches/`，而非 `platform/rockchip/patches/`

### Requirement: 三层职责分离
项目的工程结构 SHALL 遵循三层职责分离：`platform/` 负责声明"用什么"（配置值），组件平台子目录负责"怎么做"（构建实现和平台通用数据），`board/` 负责"板子特殊化"（板级补丁、DTS、overlay）。

#### Scenario: 新增一个 Rockchip 板子
- **WHEN** 需要新增 rk3568-custom 板子支持
- **THEN** 在 `board/rk3568-custom/` 下创建 `board.bzl`（板级配置）和 `patches/`（板级补丁），复用 `kernel/rockchip/` 的平台构建逻辑和 `platform/rockchip/` 的平台配置，无需修改组件平台子目录

### Requirement: 补丁归属判断规则
影响该平台所有板子的补丁 SHALL 放置在组件平台子目录（如 `kernel/rockchip/patches/`），仅影响特定板子的补丁 SHALL 放置在板级目录（如 `board/rk3588-evb/patches/kernel/`）。

#### Scenario: 平台通用补丁归属
- **WHEN** 一个内核补丁修复了所有 Rockchip 芯片的公共问题
- **THEN** 该补丁放置在 `kernel/rockchip/patches/`

#### Scenario: 板级特有补丁归属
- **WHEN** 一个内核补丁仅修复 rk3588-evb 开发板的 PCIe 问题
- **THEN** 该补丁放置在 `board/rk3588-evb/patches/kernel/`
