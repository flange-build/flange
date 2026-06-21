## ADDED Requirements

### Requirement: kernel 顶层 alias + select() 路由
`kernel/BUILD.bazel` SHALL 定义一个 `alias` target，通过 `select()` 根据平台 `config_setting` 路由到对应平台子目录的内核构建目标。用户执行 `bazel build //kernel` 时 SHALL 自动路由到当前配置的平台实现。

#### Scenario: Rockchip 平台路由
- **WHEN** 使用 `--config=radxa-zero3w`（平台为 rockchip）执行 `bazel build //kernel`
- **THEN** 实际构建 `//kernel/rockchip` target

#### Scenario: 未配置平台时构建失败
- **WHEN** 执行 `bazel build //kernel` 但未指定任何 `--config`
- **THEN** Bazel 报错，提示需要指定平台配置

### Requirement: 新增平台只需扩展 select()
新增平台的内核支持时，SHALL 只需在 `kernel/BUILD.bazel` 的 `select()` 中增加一行映射，无需修改其他文件。

#### Scenario: 添加 Allwinner 平台
- **WHEN** 需要新增 Allwinner 平台的内核构建
- **THEN** 在 `kernel/BUILD.bazel` 的 `select()` 中增加 `"//build:platform_allwinner": "//kernel/allwinner"`，并创建 `kernel/allwinner/BUILD.bazel`
