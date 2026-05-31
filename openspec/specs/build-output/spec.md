# build-output Specification

## Purpose
TBD - created by archiving change structured-output. Update Purpose after archive.
## Requirements
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
- **THEN** 系统显示 L1 + L2 + L3 全量输出，L3 输出以灰色带 `│` 前缀显示

#### Scenario: Quiet 模式构建输出

- **WHEN** 用户执行 `flange build -q`
- **THEN** 系统仅显示 L1 级别的单行摘要（组件名 + 最终状态 + 耗时）

### Requirement: 颜色编码标准

构建系统 SHALL 使用统一的 ANSI 颜色编码：

| 元素 | 颜色 | 符号 |
|------|------|------|
| 阶段标题 | 蓝色加粗 `\033[1;34m` | `▸` |
| 成功状态 | 绿色 `\033[0;32m` | `✓` |
| 警告信息 | 黄色 `\033[1;33m` | `⚠` |
| 错误信息 | 红色加粗 `\033[1;31m` | `✗` |
| 跳过状态 | 灰色 `\033[0;90m` | `⊘` |
| 工具输出 | 暗灰 `\033[0;90m` | `│` |
| 耗时数字 | 暗灰 `\033[0;90m` | — |
| 错误框线 | 红色 `\033[0;31m` | `┄` |

#### Scenario: 颜色显示

- **WHEN** 输出目标为 TTY 终端
- **THEN** 系统使用上述颜色编码渲染输出

#### Scenario: 非 TTY 环境

- **WHEN** 输出目标非 TTY（管道、文件重定向、CI 环境）
- **THEN** 系统禁用 ANSI 颜色码，输出纯文本

### Requirement: Spinner 动画与计时器

当外部命令正在执行时，系统 SHALL 显示 braille spinner 动画和实时计时器。

Spinner 字符集：`⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`

#### Scenario: 编译进行中

- **WHEN** 外部编译命令正在执行且输出模式为 NORMAL
- **THEN** 系统在状态行显示旋转 spinner + 操作描述 + 实时秒数（`\r` 原地刷新），格式如 `⠹ 编译中...                                      38s`

#### Scenario: 命令完成

- **WHEN** 外部命令成功完成
- **THEN** spinner 行被替换为成功状态行 `✓ 编译完成                                       42.3s`

#### Scenario: 非 TTY 环境无 spinner

- **WHEN** 输出目标非 TTY
- **THEN** 系统不显示 spinner 动画，仅在命令完成后打印结果行

### Requirement: 构建摘要

构建结束后（无论成功或失败），系统 SHALL 打印构建摘要。

#### Scenario: 构建成功摘要

- **WHEN** 所有组件构建成功
- **THEN** 系统打印：分隔线 + `✓ 构建完成` + 总耗时 + 各组件状态表（名称、状态（构建/跳过）、耗时、耗时占比条形图）+ 日志文件路径

#### Scenario: 构建失败摘要

- **WHEN** 某组件构建失败导致构建终止
- **THEN** 系统打印：分隔线 + `✗ 构建失败` + 已耗时 + 失败组件名称及错误摘要 + 日志文件路径

### Requirement: 错误上下文提取

命令执行失败时，系统 SHALL 提取并高亮显示错误相关行。

#### Scenario: 编译错误提取

- **WHEN** make 命令以非零 exit code 退出
- **THEN** 系统从捕获的输出中匹配错误模式（`error:`, `make\[\d+\]: \*\*\*`, `undefined reference to`），提取匹配行及上下文，用红色 `┄` 框线包裹显示

#### Scenario: 无匹配错误模式时兜底

- **WHEN** 命令失败但无错误模式匹配
- **THEN** 系统显示命令输出的最后 20 行作为兜底上下文

#### Scenario: apt 错误提取

- **WHEN** apt-get/dpkg 命令失败
- **THEN** 系统匹配 `^E:` 和 `dpkg: error` 模式行并显示

### Requirement: 日志持久化

系统 SHALL 将全量构建输出写入日志文件。

#### Scenario: 日志文件创建

- **WHEN** 构建开始
- **THEN** 系统创建（或覆盖）`target/<board>/<product>/<variant>/build.log` 文件，写入所有 L1 + L2 + L3 输出（不含 ANSI 颜色码）

#### Scenario: 摘要包含日志路径

- **WHEN** 构建摘要打印时
- **THEN** 摘要最后一行显示日志文件的完整路径

### Requirement: 统一输出接口

所有 Python 构建模块 SHALL 通过 `builder/output.py` 的 `BuildOutput` 类进行用户可见输出。

#### Scenario: 禁止直接输出

- **WHEN** Python 构建模块需要输出用户可见信息
- **THEN** 模块 MUST 使用 `BuildOutput` 的方法（`status()`、`error()`、`warning()`），MUST NOT 使用 `print()` 或 `logging.info()` 直接输出

#### Scenario: BuildOutput 未注入时的兼容

- **WHEN** `DockerRunner` 未被注入 `BuildOutput` 实例（如单元测试场景）
- **THEN** `DockerRunner.run()` 回退为 `subprocess.run()` 直通模式

### Requirement: Verbose 级别 CLI 参数

`flange build` 命令 SHALL 支持 `-v` 和 `-q` 参数控制输出级别。

#### Scenario: verbose 参数

- **WHEN** 用户执行 `flange build -v`
- **THEN** envsetup.sh 解析 `-v` 参数，传递 `verbose=True` 给 Python 引擎，BuildOutput 以 VERBOSE 级别运行

#### Scenario: quiet 参数

- **WHEN** 用户执行 `flange build -q`
- **THEN** envsetup.sh 解析 `-q` 参数，传递 `quiet=True` 给 Python 引擎，BuildOutput 以 QUIET 级别运行

#### Scenario: 默认级别

- **WHEN** 用户执行 `flange build` 无额外参数
- **THEN** BuildOutput 以 NORMAL 级别运行

### Requirement: Warning 仅 verbose 显示

构建过程中的 warning 信息（如 GCC warning）SHALL 仅在 VERBOSE 模式下显示。

#### Scenario: 默认模式忽略 warning

- **WHEN** 外部命令输出包含 `warning:` 行且输出级别为 NORMAL
- **THEN** 系统不在终端显示该 warning 行（但写入 build.log）

#### Scenario: verbose 模式显示 warning

- **WHEN** 外部命令输出包含 `warning:` 行且输出级别为 VERBOSE
- **THEN** 系统以灰色显示该 warning 行

