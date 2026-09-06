## MODIFIED Requirements

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
