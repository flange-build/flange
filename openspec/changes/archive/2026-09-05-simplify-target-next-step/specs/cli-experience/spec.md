## ADDED Requirements

### Requirement: 选择目标后引导系统构建与计划

目标选择成功后，人类可读输出 SHALL 显示“下一步  flange build 或 flange plan”，
引导用户构建当前目标的完整系统，或先预览默认系统构建计划。命令文字 SHALL 沿用统一命令语义样式。

#### Scenario: 显式选择目标成功
- **WHEN** 用户通过 `flange target select <target>` 成功选择目标且未请求 JSON 输出
- **THEN** 目标摘要后的下一步提示为 `flange build 或 flange plan`

#### Scenario: 交互选择目标成功
- **WHEN** 用户通过交互菜单或 `lunch` 成功选择目标且显示人类可读摘要
- **THEN** 下一步提示同样为 `flange build 或 flange plan`

#### Scenario: 禁用颜色后的下一步提示
- **WHEN** 目标选择成功且输出流不支持颜色或用户禁用颜色
- **THEN** 下一步提示以纯文本保留 `flange build 或 flange plan`
