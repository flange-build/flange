## MODIFIED Requirements

### Requirement: 配置注册表提供 get_board_config 函数

`builder/config/registry.py` SHALL 提供 `get_board_config(board_name)` 与 `resolve_config(board_name, product, variant)`。前者 SHALL 通过 Jsonnet evaluator 按 rootfs → platform → SoC → board 组合指定 board 的 canonical 配置；后者 SHALL 将 product/variant 作为显式 Jsonnet 求值参数并返回通过 validator 的最终 dict。注册表 MUST NOT 自行实现字段合并、条件后缀或平台专属字段翻译。

#### Scenario: 查询已注册 board 配置
- **WHEN** 调用 `get_board_config(<已注册 board>)`
- **THEN** 返回 dict 包含 rootfs、platform、SoC 与 board overlay 求值后的 canonical 字段

#### Scenario: board 层覆盖 SoC 层同名字段
- **WHEN** SoC 与 board overlay 声明同一个可覆盖 canonical 字段
- **THEN** `get_board_config()` 返回 board 值

#### Scenario: 解析完整 lunch target
- **WHEN** 调用 `resolve_config(board, product, variant)`
- **THEN** Jsonnet 条件按独立 product/variant 参数求值
- **AND** 返回值通过 canonical validator

### Requirement: 查询不存在的板子名称时报错

`get_board_config()` 和 `resolve_config()` 在传入未发现的 board 名称时 SHALL 立即抛出明确错误，错误信息 MUST 包含 board 名称和可用 board 列表，且不得开始 Jsonnet 全量求值或构建。

#### Scenario: 未注册的板子名称
- **WHEN** 调用 `resolve_config("unknown-board", "default", "debug")`
- **THEN** 抛出包含 `unknown-board` 和可用 board 列表的错误

### Requirement: 注册表导出已注册板子列表

`discover_boards()` SHALL 通过扫描 `components/board/*/config.jsonnet` 自动返回已注册 board 及其身份元数据；lunch target 查询 SHALL 基于每个 board 声明的 products 与 variants 生成列表，不得维护硬编码 `REGISTERED_BOARDS`。

#### Scenario: 获取已注册 board 列表
- **WHEN** 调用 `discover_boards()`
- **THEN** 返回所有合法 `components/board/*/config.jsonnet` 的 board 名称
- **AND** 排除缺少必需身份字段或身份与目录名不一致的配置
