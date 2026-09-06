## MODIFIED Requirements

### Requirement: 分层输出结构

构建系统 SHALL 将输出分为三个层级：

| 层级 | 内容 | 显示条件 |
|------|------|---------|
| L1 阶段标题 | 组件名 + 状态标记 | 始终显示 |
| L2 状态行 | 阶段进度、缓存决策、关键事件 | NORMAL 和 VERBOSE 显示 |
| L3 工具输出 | make/git/apt 等外部命令原始输出 | 仅 VERBOSE 全量显示；NORMAL 仅显示错误行 |

#### Scenario: 默认模式构建输出

- **WHEN** 用户执行 `flange build` 未指定 verbose 标志
- **THEN** 系统显示 L1 阶段标题和 L2 状态行，L3 工具输出被压缩（仅在命令失败时显示错误上下文）

#### Scenario: Verbose 模式构建输出

- **WHEN** 用户执行 `flange build -v`
- **THEN** 系统显示 L1 + L2 + L3 全量输出，L3 输出使用降低亮度的默认前景色并带 `│` 前缀

#### Scenario: Quiet 模式构建输出

- **WHEN** 用户执行 `flange build -q`
- **THEN** 系统仅显示 L1 级别的单行摘要（组件名 + 最终状态 + 耗时）

### Requirement: 颜色编码标准

构建系统 SHALL 用统一颜色和文字状态表达阶段、成功、警告、失败与复用，并与公共命令、刷写和目标选择共享语义颜色来源。标题、正常需构建与进行中 SHALL 使用蓝色，成功与缓存复用 SHALL 使用绿色，警告、受阻待准备与取消 SHALL 使用黄色，错误与失败 SHALL 使用红色，路径与命令 SHALL 使用青色；正文 SHALL 使用终端默认前景，次要说明 SHALL 降低亮度。

颜色只是辅助信息，输出到非 TTY、`TERM=dumb`、设置 `NO_COLOR` 或指定 `--no-color` 时 SHALL 不输出 ANSI 控制码。状态文字、状态符号与错误原文 SHALL 在降级后保持可读。正常缓存未命中 SHALL 表示待构建而非失败；颜色选择不得改变缓存判断、日志内容或退出码。

#### Scenario: 有能力的交互终端

- **WHEN** 输出为 TTY 且没有禁用颜色
- **THEN** 阶段、正常需构建与进行中使用蓝色，成功和复用使用绿色，警告与受阻待准备使用黄色，失败使用红色，并保留对应状态文字或符号

#### Scenario: 无颜色输出

- **WHEN** 用户指定 `--no-color`，设置包括空值在内的 `NO_COLOR`，设置 `TERM=dumb`，或输出到管道
- **THEN** 输出保留文字含义且不包含 ANSI 颜色与光标控制码

#### Scenario: 正常缓存未命中

- **WHEN** 首次构建或输入变化导致组件需要构建
- **THEN** 需构建状态与执行阶段使用蓝色正常待执行或进行中语义，不呈现黄色警告或红色失败状态

#### Scenario: 缓存复用

- **WHEN** 组件满足缓存复用条件而跳过执行
- **THEN** 复用状态使用绿色，并保留跳过或复用文字与符号，不报告虚构执行耗时

#### Scenario: 用户取消

- **WHEN** 构建收到用户中断且输出到有颜色能力的终端
- **THEN** 取消结果使用黄色，保留取消文字，不显示绿色成功结果

### Requirement: Warning 仅 verbose 显示

构建过程中的 warning 信息（如 GCC warning）SHALL 仅在 VERBOSE 模式下显示。

#### Scenario: 默认模式忽略 warning

- **WHEN** 外部命令输出包含 `warning:` 行且输出级别为 NORMAL
- **THEN** 系统不在终端显示该 warning 行（但写入 build.log）

#### Scenario: verbose 模式显示 warning

- **WHEN** 外部命令输出包含 `warning:` 行且输出级别为 VERBOSE
- **THEN** 系统将该 warning 行作为工具原始输出，以降低亮度的默认前景色显示
