## MODIFIED Requirements

### Requirement: flange push / run 热部署

`flange push app <app>` SHALL 把单个 App 的产物部署到目标设备；`flange run app <app>` SHALL 在部署
之后立即运行它。两者 SHALL 作为兼容入口保留，并与 `flange app deploy <app>`、
`flange app run <app>` 使用相同实现。

#### Scenario: 热部署

- **WHEN** 执行 `flange push app demo`
- **THEN** demo 的产物被部署到设备，不需要重新刷写整机镜像

#### Scenario: 旧入口与资源优先入口一致

- **WHEN** 对相同 target 与 App 分别执行 `flange run app demo` 和 `flange app run demo`
- **THEN** 两个入口使用相同的 App 解析、构建、部署和启动语义

## ADDED Requirements

### Requirement: App 与 Package SHALL 提供资源优先命令组

CLI SHALL 提供 `flange app create|build|deploy|run|debug|log` 与
`flange package create|build|deploy|run|debug|log`。帮助文本 SHALL 展示子命令、target/path 参数、设备选择
参数和 `--` 透传边界。`build app`、`create app`、`push app`、`run app` 等既有入口 SHALL 保持可用。

#### Scenario: 查看 App 命令帮助

- **WHEN** 执行 `flange app --help`
- **THEN** 输出 create、build、deploy、run、debug、log 及其参数说明

#### Scenario: 旧 App build 入口保持可用

- **WHEN** 执行 `flange build app demo`
- **THEN** 命令继续构建 demo，且产物布局与 `flange app build demo` 一致
