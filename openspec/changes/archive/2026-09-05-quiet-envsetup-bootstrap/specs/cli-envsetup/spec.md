## MODIFIED Requirements

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
