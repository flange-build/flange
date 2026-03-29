## MODIFIED Requirements

### Requirement: 组件目录遵循顶层 alias + select() 路由模式
每个嵌入式组件（kernel、bootloader 等）SHALL 在顶层目录提供 alias target，通过 `select()` 按平台 `config_setting` 路由到 `<component>/<platform>/` 子目录的具体实现。每个平台子目录包含 `BUILD.bazel`（规则实例化）和 `build.sh`（平台策略脚本）。

#### Scenario: kernel 组件遵循此模式
- **WHEN** 查看 `kernel/BUILD.bazel`
- **THEN** 包含 alias 通过 `select()` 路由到 `//kernel/rockchip`

#### Scenario: bootloader 组件遵循此模式
- **WHEN** 查看 `bootloader/BUILD.bazel`
- **THEN** 包含 alias 通过 `select()` 路由到 `//bootloader/rockchip`
