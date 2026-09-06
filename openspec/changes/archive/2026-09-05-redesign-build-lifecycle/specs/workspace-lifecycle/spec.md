## ADDED Requirements

### Requirement: 工作区显式管理目标与输出
工作区 MUST 通过 flange.toml 声明工具根、App 搜索目录与输出根，独立保存目标选择。
CLI MUST 使用 WorkspaceContext 传递路径与目标，MUST NOT 将全局 shell 状态作为操作身份。

#### Scenario: 两个外部项目独立选择目标
- **WHEN** 两个工作区分别选择不同 target 并构建同名 App
- **THEN** 两者目标状态、工作目录和产物互不覆盖

### Requirement: 安装入口在源码树外可用
flange MUST 提供 Python 安装命令入口、模块入口与工作区初始化命令，模板 MUST 随安装包分发。

#### Scenario: 外部目录创建并构建 App
- **WHEN** 已安装 flange 并在外部工作区创建 App
- **THEN** 无需修改工具仓库配置即可解析目标、构建并定位产物

### Requirement: 宿主与容器路径一致
工作区、工具根和显式输入 MUST 经统一挂载计划映射，容器不得重新解释宿主用户目录。

#### Scenario: 绝对与相对外部 App
- **WHEN** 同一 App 由路径、名称或 cwd 请求
- **THEN** 所有入口使用相同源码身份及实际目录
