## ADDED Requirements

### Requirement: App 构建期 APT 依赖由 app.yaml 声明

需要系统开发包的 App MUST 在 `build.apt_packages` 中声明构建期 APT 依赖，构建系统 MUST 在当前构建容器内、编译命令
执行前安装这些包。包名 MAY 使用 `:{arch}` 占位符选择当前目标架构。App 专属构建依赖 MUST NOT 固化到通用
`docker/Dockerfile`；`build.deps` 与顶层 `depends` 的 App 间依赖、设备运行时依赖语义 MUST 保持不变。

#### Scenario: ARM32 App 声明交叉编译开发包

- **WHEN** armhf App 声明 `build.apt_packages: [libasound2-dev:{arch}]` 并开始编译
- **THEN** 构建系统先在当前容器安装 `libasound2-dev:armhf`，再执行该 App 的构建命令

#### Scenario: App 同时声明构建期与运行期依赖

- **WHEN** App 在 `build.apt_packages` 声明 `libasound2-dev:{arch}`，并在顶层 `depends` 声明 `libasound2t64`
- **THEN** 前者仅安装到构建容器，后者仅写入目标 `.deb` 的运行时依赖

#### Scenario: 构建依赖包含非法 APT 参数

- **WHEN** `build.apt_packages` 中出现以 `-` 开头的参数、shell 片段或无效架构占位符
- **THEN** `app.yaml` 解析阶段给出明确错误并停止构建
