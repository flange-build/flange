# cli-envsetup Specification

## Purpose

定义 `envsetup.sh` 的环境初始化契约：source 之后提供什么、`lunch` 如何交互式选择目标、以及各子命令执行前必须通过哪些前置检查。
## Requirements
### Requirement: envsetup.sh 初始化开发环境

项目根目录 SHALL 提供仅承担 venv 初始化和薄入口的 envsetup.sh。正式 flange 命令 MUST 来自 Python 安装入口；lunch SHALL 是 target select 的薄包装。Shell MUST NOT 包含构建、配置解析和设备编排逻辑。初始化 MUST NOT 主动启用 xtrace（命令跟踪），并 MUST 保留必要的入口提示、失败诊断和调用者原有的 Shell 执行选项。

#### Scenario: 任意目录初始化
- **WHEN** 用户 source 工具仓库的 envsetup.sh
- **THEN** 安装并启用 flange 命令，设置 FLANGE_DIR 指向工具根，调用者 cwd 与 Shell 执行选项保持不变

#### Scenario: 默认初始化输出
- **WHEN** 用户未开启 xtrace 并成功 source envsetup.sh
- **THEN** 输出必要的初始化提示，不输出 `+_flange_bootstrap` 等命令跟踪

#### Scenario: 安装失败恢复
- **WHEN** 已有 venv 但依赖不可导入，或者 pyproject.toml 已变更
- **THEN** 重新执行安装，只有安装成功才记录就绪状态；失败诊断仍可见，失败后下次初始化仍可重试

### Requirement: lunch 交互式板级选择

lunch SHALL 转发至 flange target select。标准输入输出为 TTY、允许交互且未指定目标时 SHALL 展示平台、SoC、board、product、variant 层级树。导航 SHALL 从身份投影构造，完整配置摘要 SHALL 后台加载。选中目标完整解析成功后 SHALL 原子保存当前工作区状态。

#### Scenario: 定位并选择
- **WHEN** 已有目标的工作区运行 lunch
- **THEN** 界面定位到当前目标；选定后显示目标、工作区与下一步命令

#### Scenario: 取消选择
- **WHEN** 用户取消交互界面
- **THEN** 返回取消状态，当前工作区目标不变

#### Scenario: 自动化选择
- **WHEN** 非 TTY 或 --no-interaction 模式省略目标名
- **THEN** 立即返回参数错误，提示 target list 与 target select，不读取 stdin

#### Scenario: 完整目标名
- **WHEN** 运行 lunch radxa-rock5b-desktop-debug
- **THEN** 从板级注册表解析并校验完整目标，成功后保存到当前工作区，不进入菜单

### Requirement: 前置检查

CLI SHALL 只检查当前操作需要的条件。工作区发现、目标选择、配置求值、Docker 与设备访问 MUST 保持明确边界。

#### Scenario: 未选目标
- **WHEN** 已初始化但未选目标的工作区请求构建
- **THEN** 返回配置错误并提示 target list 和 target select

#### Scenario: 只读计划
- **WHEN** Docker 不可用时查询 plan
- **THEN** 仍可展示已知计划，同时标注未确认的环境输入；不启动构建容器

#### Scenario: 容器构建镜像缺失
- **WHEN** 构建需要的镜像不可用
- **THEN** 返回操作失败并提示 flange docker build，不执行目标编译
