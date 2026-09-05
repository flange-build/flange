# cli-experience Specification

## Purpose

定义 flange 面向开发者与自动化的命令交互规范，覆盖命令发现、稳定机器输出、非交互操作、错误恢复和终端能力降级，使外部工作区的完整开发旅程具有一致且可解释的反馈。
## Requirements
### Requirement: 人和自动化共用稳定命令边界

CLI SHALL 支持工作区和目标的显式覆盖、版本化 JSON 结果以及无交互模式。未知选项 MUST 失败而不是被忽略。

#### Scenario: 管道读取机器结果
- **WHEN** 用户运行 flange --json status
- **THEN** stdout 只含一份具有 schema_version、command、ok 和 data 的 JSON 文档，无 ANSI 颜色或进度文本

#### Scenario: 无交互选择目标
- **WHEN** 用户在无 TTY 或 --no-interaction 模式省略 target select 的目标参数
- **THEN** 命令立即以退出码 2 返回明确的目标列举与选择指引，不等待 stdin

### Requirement: 诊断可恢复且结果真实

CLI SHALL 使用稳定退出码区分成功、操作失败、参数或配置错误及取消。失败信息 MUST 保留定位所需的信息，并给出适用的恢复步骤。

#### Scenario: 缺少目标
- **WHEN** 工作区尚未选目标而用户请求构建
- **THEN** 命令指出使用 target list 和 target select，不输出 Python 堆栈

#### Scenario: 用户取消构建
- **WHEN** 构建收到用户中断
- **THEN** 命令停止当前子进程并释放资源，以 130 退出，已有日志可读且不产生新的成功产物清单

#### Scenario: 默认系统构建失败后恢复

- **WHEN** 用户请求默认 image 构建且内部阶段失败
- **THEN** 人类诊断集中说明一次根因和日志位置，提示修复后执行 flange build
- **AND** 不默认要求删除缓存或 force 重建

#### Scenario: 指定组件构建失败后恢复

- **WHEN** 用户请求 flange build kernel 且执行失败
- **THEN** 恢复指引保留 kernel 组件及适用的工作区和临时目标，不改成无关构建请求

### Requirement: 终端视觉按能力降级

终端呈现 SHALL 支持中文宽度、窄终端和无颜色环境。非 TTY 输出 MUST 没有光标控制与动画，语义不能仅由颜色表达。颜色能力 SHALL 根据本次实际输出流动态判断，stdout 与 stderr SHALL 分别遵循各自的终端能力。

#### Scenario: 禁用颜色
- **WHEN** 用户设置包括空值在内的 NO_COLOR、使用 --no-color，或 TERM 为 dumb
- **THEN** 公共命令、构建、刷写和目标选择输出不产生 ANSI 颜色和动画，状态文字与符号保持可读

#### Scenario: 窄终端构建摘要
- **WHEN** 终端宽度不足以容纳完整阶段或结果行
- **THEN** 摘要使用可折行的文本记录，组件、结果和耗时仍然可读

#### Scenario: stdout 重定向而 stderr 仍为终端
- **WHEN** 人类可读结果输出到文件且诊断仍输出到有颜色能力的 stderr
- **THEN** stdout 不含颜色或光标控制码，stderr 独立按自身能力决定是否着色

#### Scenario: 运行期间替换输出流
- **WHEN** 终端输出模块加载后实际输出流变为非 TTY
- **THEN** 随后的样式调用输出纯文本，不沿用加载时的终端能力

### Requirement: 计划预览不执行构建

CLI SHALL 在不下载源码、不启动编译、不修改成功记录的条件下展示依赖和输出，并明确标注未解析的执行输入。

#### Scenario: 首次构建前预览
- **WHEN** 用户在新工作区运行 flange plan image
- **THEN** 命令展示任务顺序、依赖和预期产物，不创建构建产物或执行设备操作

### Requirement: 公共命令按语义角色统一着色

公共命令、构建、刷写和目标选择 SHALL 共享语义颜色定义：标题、正常需构建与进行中为蓝色，成功与可复用为绿色，警告、受阻待准备与取消为黄色，错误与失败为红色，路径与命令为青色，正文保留终端默认前景，次要说明降低亮度。颜色 SHALL 由结构化结果的真实状态或调用方明确的语义角色决定，不得仅匹配整段显示文本来推断业务状态。JSON 结果与持久化日志 MUST 保持纯文本。

#### Scenario: 缓存可复用
- **WHEN** why 的结果确认输入与产物满足复用条件，并输出到有颜色能力的终端
- **THEN** 可复用状态以绿色显示，同时保留明确的可复用文字

#### Scenario: 正常缓存未命中
- **WHEN** why 的结果表明首次构建或输入变化导致需要构建，且没有执行失败
- **THEN** 终端以蓝色正常待执行语义显示需构建状态，不使用黄色警告或红色失败语义，也不改变退出码或 JSON 状态

#### Scenario: 输入尚待准备
- **WHEN** why 的结果为 blocked，缺少完成判断所需的执行输入
- **THEN** 终端以黄色显示待准备状态，并保留说明缺少条件的文字

#### Scenario: 失败与取消
- **WHEN** 命令结果分别为操作失败或用户取消，且输出到有颜色能力的终端
- **THEN** 失败使用红色，取消使用黄色，并各自保留失败或取消文字与原有退出码

#### Scenario: 路径包含状态词
- **WHEN** 输出的产物路径或命令参数包含成功、失败或 warning 等字样
- **THEN** 该内容仍按路径或命令语义显示为青色，不因文字包含状态词而改变角色

#### Scenario: JSON 与日志保持机器可读
- **WHEN** 用户请求 JSON 结果或查看持久化日志
- **THEN** 内容不含终端颜色与光标控制码，JSON 使用原始结果数据且 stderr 过程也不添色，JSON 字段与日志文字不受语义着色影响

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
