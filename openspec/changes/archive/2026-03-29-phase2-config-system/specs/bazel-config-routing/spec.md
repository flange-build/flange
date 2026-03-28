## ADDED Requirements

### Requirement: platform 级 config_setting 定义
`build/BUILD.bazel` SHALL 定义 platform 级的 `config_setting` 规则，匹配 `--define platform=<vendor>` flag。首个实例为 `platform_rockchip`。

#### Scenario: config_setting 匹配 Rockchip 平台
- **WHEN** 构建时传入 `--define=platform=rockchip`
- **THEN** `//build:platform_rockchip` config_setting 匹配成功

### Requirement: board 级 config_setting 定义
`build/BUILD.bazel` SHALL 定义 board 级的 `config_setting` 规则，匹配 `--define board=<name>` flag。首个实例为 `board_radxa_zero3w`。

#### Scenario: config_setting 匹配 radxa-zero3w
- **WHEN** 构建时传入 `--define=board=radxa-zero3w`
- **THEN** `//build:board_radxa_zero3w` config_setting 匹配成功

### Requirement: .bazelrc 提供板级快捷配置
`.bazelrc` SHALL 为每个已注册板子提供 `build:<board-name>` 配置，映射到正确的 platform、board define 和 platforms flag。

#### Scenario: --config=radxa-zero3w 设置所有必要 flag
- **WHEN** 使用 `--config=radxa-zero3w` 构建
- **THEN** 等效于设置 `--platforms=//toolchain:aarch64_linux`、`--define=platform=rockchip`、`--define=board=radxa-zero3w`

### Requirement: config_setting 具有公共可见性
`build/BUILD.bazel` 中的 `config_setting` 规则 SHALL 设置 `visibility = ["//visibility:public"]`，使所有组件目录的 `select()` 均可引用。

#### Scenario: 组件目录可引用 config_setting
- **WHEN** `kernel/BUILD.bazel` 中使用 `select({"//build:platform_rockchip": ...})`
- **THEN** 构建不报 visibility 错误
