## MODIFIED Requirements

### Requirement: App 身份由 app.yaml 声明，目录名仅用于物理定位

每个 App SHALL 在其根目录内提供一个 `app.yaml`，其中 `app.name` 字段是 App 的权威身份；App 目录名本身
不作为身份，仅用于在宿主机上定位。构建系统 SHALL 在加载 App 时以 `app.yaml` 的 `app.name` 为准。
`app.name` 与 `app.version` MUST 是可安全用于工作目录、deb 文件名与 control 字段的单行标识符；路径分隔符、
空白、控制字符与 glob 元字符 MUST 被拒绝。

#### Scenario: 目录名与 app.name 不一致

- **WHEN** App 根目录名为 `bar-legacy`，其中 `app.yaml` 内 `app.name: bar`
- **THEN** 构建系统加载后使用的 App 名称为 `bar`

#### Scenario: App 身份包含路径遍历

- **WHEN** 外部 App 声明 `app.name: ../../escape` 或 `app.version: 1.0/../../escape`
- **THEN** 清单加载失败
- **AND** 构建系统不删除或写入 App 工作目录及 target 输出目录之外的路径

## ADDED Requirements

### Requirement: flange app create SHALL 默认创建到调用者目录

资源优先入口 `flange app create <name>` 在未传 `--dir` 时 SHALL 使用调用者当前目录作为父目录；
`flange create app <name>` 的默认位置 SHALL 继续是 `<project_root>/components/app/`。两个入口显式传
`--dir` 时 SHALL 使用相同的路径展开、目标存在校验和脚手架内容。

#### Scenario: 在仓库外使用资源优先入口创建 App

- **WHEN** 用户在 `/work/vendor` 执行 `flange app create demo`
- **THEN** App 创建于 `/work/vendor/demo`
- **AND** 命令不自动修改 external_apps 或 external_app_dirs

#### Scenario: 旧入口默认位置保持不变

- **WHEN** 用户执行 `flange create app demo` 且未传 `--dir`
- **THEN** App 创建于 `<project_root>/components/app/demo`

### Requirement: ad-hoc App 路径 SHALL 优先于 registry 名称解析

资源优先 App 命令的目标若为已存在的目录或显式路径表达式，SHALL 直接校验该目录中的 `app.yaml`；否则
SHALL 按既有 local、external_apps、external_app_dirs 优先级把目标作为名称解析。相对路径 SHALL 基于
调用者 cwd，仓库外路径 SHALL 在启动最外层构建容器前加入 bind mount。

#### Scenario: 从仓库外当前目录构建 App

- **WHEN** 当前目录 `/work/demo` 含 `app.yaml` 且用户执行 `flange app build`
- **THEN** CLI 构建 `/work/demo`
- **AND** Docker 构建阶段可访问相同绝对路径的完整源目录
