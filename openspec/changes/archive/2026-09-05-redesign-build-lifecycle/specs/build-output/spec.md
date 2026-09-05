## MODIFIED Requirements

### Requirement: 颜色编码标准

构建系统 SHALL 用统一颜色和文字状态表达阶段、成功、警告、失败与复用。颜色只是辅助信息，
输出到非 TTY、`TERM=dumb`、设置 `NO_COLOR` 或指定 `--no-color` 时 SHALL 不输出 ANSI 控制码。
状态文字与错误原文 SHALL 在降级后保持可读。

#### Scenario: 有能力的交互终端

- **WHEN** 输出为 TTY 且没有禁用颜色
- **THEN** 阶段、成功、警告与失败使用一致的颜色及状态文字

#### Scenario: 无颜色输出

- **WHEN** 用户指定 `--no-color`，设置包括空值在内的 `NO_COLOR`，或输出到管道
- **THEN** 输出保留文字含义且不包含 ANSI 颜色与光标控制码

### Requirement: Spinner 动画与计时器

NORMAL 模式的交互终端 SHALL 显示实际步骤与耗时；非 TTY、无颜色模式和 QUIET 模式 SHALL
禁用 spinner 与光标重绘。进度 SHALL 只代表已完成任务比例，不得虚构剩余时间或跳过耗时。
窄终端 SHALL 按实际显示宽度截断活动行，完整错误与日志位置仍可读取。

#### Scenario: 编译进行中

- **WHEN** 外部编译命令执行且 NORMAL 输出终端支持颜色与重绘
- **THEN** 状态行显示当前操作和实际已耗时，完成后转换为结果行

#### Scenario: 无动画环境

- **WHEN** 输出到管道、无颜色终端或 QUIET 模式
- **THEN** 系统输出文本阶段与结果，不执行 spinner 或光标重绘

### Requirement: 日志持久化

系统 SHALL 将完整构建输出写入 `WorkspaceContext.target_dir/build.log`，不含 ANSI 控制码。
系统与独立 App/Package 构建 SHALL 在取得目标锁后初始化日志，轮转已有日志后再开始新构建，
并在成功、失败或取消时关闭日志。终端摘要 SHALL 提供完整日志路径。

#### Scenario: 独立资源构建

- **WHEN** 用户在外部工作区执行 `flange app build` 或 `flange package build`
- **THEN** 原始工具输出写入该工作区目标日志，终端默认只显示阶段与摘要

#### Scenario: 并发与失败

- **WHEN** 第二个构建等待相同目标锁，或执行中的构建失败或取消
- **THEN** 等待者不会提前轮转日志，执行者保留完整日志且不会呈现成功摘要

### Requirement: Verbose 级别 CLI 参数

`flange build`、`flange app build` 和 `flange package build` SHALL 支持互斥的
`-v/--verbose` 与 `-q/--quiet`。Python CLI SHALL 将输出级别作为执行参数传给输出服务，
不得混入决定构建内容的配置或指纹。

#### Scenario: verbose 参数

- **WHEN** 用户为构建命令指定 `-v`
- **THEN** BuildOutput 以 VERBOSE 级别显示完整工具输出并继续记录日志

#### Scenario: quiet 参数

- **WHEN** 用户为构建命令指定 `-q`
- **THEN** BuildOutput 只呈现摘要与必要的失败上下文

#### Scenario: 默认级别

- **WHEN** 用户不指定输出级别
- **THEN** 构建使用 NORMAL 级别，完整编译器输出仍写入日志
