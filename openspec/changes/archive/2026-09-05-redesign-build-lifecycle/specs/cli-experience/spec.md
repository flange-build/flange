## ADDED Requirements

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

### Requirement: 终端视觉按能力降级

终端呈现 SHALL 支持中文宽度、窄终端和无颜色环境。非 TTY 输出 MUST 没有光标控制与动画，语义不能仅由颜色表达。

#### Scenario: 禁用颜色
- **WHEN** 用户设置 NO_COLOR 或使用 --no-color
- **THEN** 所有构建与刷写输出不产生 ANSI 颜色和动画

#### Scenario: 窄终端构建摘要
- **WHEN** 终端宽度不足以容纳耗时表
- **THEN** 摘要降级为可折行的文本记录，组件、结果和耗时仍然可读

### Requirement: 计划预览不执行构建

CLI SHALL 在不下载源码、不启动编译、不修改成功记录的条件下展示依赖和输出，并明确标注未解析的执行输入。

#### Scenario: 首次构建前预览
- **WHEN** 用户在新工作区运行 flange plan image
- **THEN** 命令展示任务顺序、依赖和预期产物，不创建构建产物或执行设备操作
