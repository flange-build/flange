## MODIFIED Requirements

### Requirement: 配置注册表提供 get_board_config 函数

registry SHALL 提供 get_board_config(board_name) 与 resolve_config(board_name, product, variant)，并接受显式 project_root 作为工具内容根。
前者使用 board 声明的第一个 product/variant，后者使用调用者明确目标；两者都按固定 Jsonnet 组合和 Package 展开返回严格校验结果。
工作区入口 MUST 通过 workspace.resolve_config(context) 传入 tool_root，不得把调用目录或 workspace_root 当作系统配置根。

#### Scenario: 查询已注册 board 配置
- **WHEN** 调用 get_board_config 且 board 声明多个 product/variant
- **THEN** 使用各自首个值求值并返回校验后的 canonical dict

#### Scenario: board 覆盖 SoC
- **WHEN** SoC 和 board 定义同一可覆盖字段
- **THEN** get_board_config 返回 board 的最终值

#### Scenario: 外部工作区解析目标
- **WHEN** 工作区与工具 checkout 不同目录
- **THEN** 系统配置来自 context.tool_root，目标状态只保存于 workspace_root

### Requirement: 注册表导出已注册板子列表

discover_boards SHALL 扫描工具根 components/board/*/config.jsonnet，严格校验 board 身份及非空、无重复的 products/variants。
不合法身份或目录不一致 MUST 报错，不得把损坏配置静默隐藏。目标列表 MUST 从这些维度生成，不维护硬编码注册表。

#### Scenario: 获取已注册 board 列表
- **WHEN** 全部 board 身份合法
- **THEN** 返回全部板卡身份，供 target 查询组合合法目标

#### Scenario: 板卡身份损坏
- **WHEN** board 身份与目录不一致或 products/variants 不是合法非空列表
- **THEN** 发现过程失败并指出配置问题
