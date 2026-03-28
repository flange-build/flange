### Requirement: 配置注册表提供 get_board_config 函数
`build/config_registry.bzl` SHALL 提供 `get_board_config(board_name)` 函数，接受板子名称字符串，返回经过三层合并（platform → SoC → board）的完整配置 dict。

#### Scenario: 查询 radxa-zero3w 配置
- **WHEN** 调用 `get_board_config("radxa-zero3w")`
- **THEN** 返回的 dict 包含 platform 层（如 `vendor`）、SoC 层（如 `soc`）和 board 层（如 `board`、`dts`）的合并结果

#### Scenario: board 层覆盖 SoC 层同名 key
- **WHEN** platform 层定义 `{"kernel": {"defconfig": "generic_defconfig"}}`，board 层定义 `{"kernel": {"defconfig": "board_specific_defconfig"}}`
- **THEN** `get_board_config()` 返回的 dict 中 `kernel.defconfig` 为 `"board_specific_defconfig"`

### Requirement: 查询不存在的板子名称时报错
`get_board_config()` 在传入未注册的板子名称时 SHALL 立即 `fail()`，给出包含板子名称的明确错误信息。

#### Scenario: 未注册的板子名称
- **WHEN** 调用 `get_board_config("unknown-board")`
- **THEN** Bazel 报错，错误信息包含 `"unknown-board"` 和 `"未注册"` 或类似提示

### Requirement: 注册表导出已注册板子列表
`build/config_registry.bzl` SHALL 导出 `REGISTERED_BOARDS` 列表或函数，供其他规则查询所有已注册的板子名称。

#### Scenario: 获取已注册板子列表
- **WHEN** 查询 `REGISTERED_BOARDS`
- **THEN** 返回包含 `"radxa-zero3w"` 的列表
