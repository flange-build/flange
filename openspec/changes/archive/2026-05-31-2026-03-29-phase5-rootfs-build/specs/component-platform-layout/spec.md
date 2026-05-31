## MODIFIED Requirements

### Requirement: 组件目录按平台分子目录
差异度高的组件目录（kernel、bootloader、image、rootfs）SHALL 按平台建立子目录，每个子目录包含独立的 `BUILD.bazel` 和平台特有的构建脚本、补丁文件。

#### Scenario: kernel 目录包含平台子目录
- **WHEN** 查看 kernel/ 目录结构
- **THEN** 存在 rockchip/、allwinner/、qualcomm/ 等平台子目录，每个子目录包含 `BUILD.bazel`

#### Scenario: rootfs 目录包含平台子目录
- **WHEN** 查看 rootfs/ 目录结构
- **THEN** 存在 rockchip/ 等平台子目录，每个子目录包含 `BUILD.bazel` 和 `build.sh`

### Requirement: 组件目录遵循顶层 alias + select() 路由模式
每个嵌入式组件（kernel、bootloader、rootfs 等）SHALL 在顶层目录提供 alias target，通过 `select()` 按平台 `config_setting` 路由到 `<component>/<platform>/` 子目录的具体实现。每个平台子目录包含 `BUILD.bazel`（规则实例化）和 `build.sh`（平台策略脚本）。

#### Scenario: kernel 组件遵循此模式
- **WHEN** 查看 `kernel/BUILD.bazel`
- **THEN** 包含 alias 通过 `select()` 路由到 `//kernel/rockchip`

#### Scenario: bootloader 组件遵循此模式
- **WHEN** 查看 `bootloader/BUILD.bazel`
- **THEN** 包含 alias 通过 `select()` 路由到 `//bootloader/rockchip`

#### Scenario: rootfs 组件遵循此模式
- **WHEN** 查看 `rootfs/BUILD.bazel`
- **THEN** 包含 alias 通过 `select()` 路由到 `//rootfs/rockchip`

#### Scenario: 新增平台只需在顶层加一行
- **WHEN** 需要新增 Amlogic 平台的 kernel 支持
- **THEN** 只需在 `kernel/BUILD.bazel` 的 `select()` 中增加一行 `"//config:amlogic": "//kernel/amlogic"`
