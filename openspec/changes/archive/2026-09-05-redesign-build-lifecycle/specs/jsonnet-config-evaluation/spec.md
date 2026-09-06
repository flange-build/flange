## MODIFIED Requirements

### Requirement: flange 自带 Jsonnet 求值运行时

项目 MUST 固定并声明 Python Jsonnet 求值依赖，`flange target select`、`lunch`、`flange build` 和配置查询不得要求 PATH 中安装 jsonnet CLI。
运行时缺失或版本不兼容 MUST 在配置加载阶段给出明确安装错误。

#### Scenario: PATH 中没有 jsonnet CLI
- **WHEN** PATH 不含 jsonnet 可执行文件但项目 Python 依赖完整
- **THEN** 目标发现、选择与构建配置解析正常工作
