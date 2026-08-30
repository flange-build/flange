# python-app-packaging Specification

## Purpose

定义 AppSpec、AppBuilder 与 DebBuilder 驱动的 Python App 解析、构建、打包和 rootfs 集成契约。
## Requirements
### Requirement: app.yaml SHALL 是 App 构建与打包的唯一数据源

每个 App SHALL 在 `components/app/<name>/app.yaml` 或已注册外部 App 根目录声明身份、版本、类型、架构、构建系统、安装映射、依赖和 systemd/deb 元数据。`AppSpec` SHALL 使用安全 YAML 解析并在构建前校验字段类型与必填项；App 构建不得依赖 BUILD.bazel 或 Starlark。

#### Scenario: 加载合法 service App

- **WHEN** app.yaml 声明完整的 app、maintainer、build、install 与 systemd 字段
- **THEN** `load_spec()` 返回带默认值的 `AppSpec`，供后续编译和打包使用

#### Scenario: 缺失必填字段

- **WHEN** app.yaml 缺少 App 名称、版本或声明了未知 build.system
- **THEN** 配置加载在执行编译前失败并指出具体字段

### Requirement: DebBuilder SHALL 生成标准 deb 产物

`DebBuilder` SHALL 根据 AppSpec 和安装文件列表生成 debian-binary、control archive 与 data archive，并组合为 `.deb`。control metadata、conffiles、postinst、prerm、文件权限和目标路径 MUST 与声明一致；所有维护脚本 MUST 避免未转义 shell 注入。

#### Scenario: service App 打包

- **WHEN** service App 声明 conffiles、自动启动 unit 和 data_dirs
- **THEN** 产物包含正确 control 字段、配置文件保护、chroot 兼容 postinst/prerm 与数据目录创建命令

#### Scenario: lib App 双包

- **WHEN** App type 为 lib
- **THEN** 构建器生成运行时包与 `-dev` 包，并把头文件和共享库安装到当前 target 的 sysroot 供下游 App 使用

### Requirement: AppBuilder SHALL 支持声明的构建系统与架构

AppBuilder SHALL 支持 none、cmake、meson、make、swift 和 custom 构建系统，在 Docker argv 中注入目标架构、交叉编译器及按需 sysroot。预编译文件 SHALL 按 arm64/aarch64/armhf 后缀选择，并按 install 映射或约定路径收集。

#### Scenario: CMake App 交叉编译

- **WHEN** aarch64 App 声明 build.system=cmake
- **THEN** Docker 收到带 aarch64 C/C++ 编译器和已解析 CPU 并行数的 configure/build argv

#### Scenario: custom 命令直通

- **WHEN** App 声明 build.system=custom 与 commands 列表
- **THEN** 构建器按声明顺序把 argv 传给 DockerRunner，不经 shell 展开

### Requirement: App 依赖与来源 SHALL 可解析

AppBuilder SHALL 按 build.deps 拓扑排序并拒绝循环依赖。SourceManager SHALL 按本地 `components/app`、`external_apps`、`external_app_dirs` 顺序定位 App，支持本地路径和 git 来源；同名来源 SHALL 遵循固定优先级。

#### Scenario: App 依赖排序

- **WHEN** service App 依赖一个 lib App
- **THEN** lib 先构建并安装 sysroot，service 后构建

#### Scenario: 外部 App 来源

- **WHEN** 本地目录未命中且 external_apps 注册合法 git 或 local_path 来源
- **THEN** SourceManager 返回该 App 根目录并使用相同 AppSpec/AppBuilder 流程构建

### Requirement: Rootfs SHALL 自动消费 App deb

构建依赖图 SHALL 保证 app 在 rootfs 之前执行。AppBuilder SHALL 把 `.deb` 输出到 `.build/target/<board>/<product>/<variant>/app/`，rootfs Phase 2 SHALL 复制这些包到 chroot 临时目录并通过 dpkg 安装，完成后清理临时文件。

#### Scenario: 构建 rootfs 自动构建 App

- **WHEN** FINAL_CONFIG 的 rootfs.custom_packages 包含 adbd 并执行 `flange build rootfs`
- **THEN** engine 先构建 adbd deb，再由 rootfs Phase 2 安装到镜像

### Requirement: CLI SHALL 提供 App 构建、发现与脚手架命令

flange CLI SHALL 支持 `flange build app [name-or-path]`、`flange list apps` 与 `flange create app <name>`。脚手架 SHALL 按 type/build-system 生成 app.yaml 和必要模板，目标已存在或生成中途失败时 MUST 不覆盖既有工程并清理不完整输出。

#### Scenario: 创建 service App

- **WHEN** 执行 `flange create app my-daemon --type=service --build-system=cmake`
- **THEN** 在目标父目录生成包含 app.yaml、CMake 源码、配置和 systemd unit 的完整工程

#### Scenario: 列出多来源 App

- **WHEN** 本地、external_apps 与 external_app_dirs 均含可用 App
- **THEN** `flange list apps` 按优先级去重并显示来源标签

### Requirement: custom vendor App SHALL 支持多个完整 DEB 输出

AppSpec MUST 接受可选的 `build.deb_outputs` 字段。该字段仅允许用于 `app.type=vendor` 且 `build.system=custom`，每一项 MUST 是
不含路径逃逸、glob 或目录成分的 `.deb` 文件名。声明后 AppBuilder MUST 校验全部输出存在并直接交付，不得再生成 wrapper DEB；
未声明时现有单 DEB 行为 MUST 保持不变。

#### Scenario: 多 DEB 输出成功

- **WHEN** custom vendor App 声明三个 `build.deb_outputs` 且命令在 app 输出目录生成对应文件
- **THEN** AppBuilder 校验并保留三个 DEB
- **AND** rootfs Phase 2 通过现有 dpkg 批次安装全部三个文件

#### Scenario: 声明输出缺失

- **WHEN** custom vendor App 未生成任一声明的 DEB
- **THEN** AppBuilder 构建失败并指出缺失文件名

#### Scenario: 非法输出声明

- **WHEN** `build.deb_outputs` 包含 `../x.deb`、`*.deb`，或用于非 vendor/custom App
- **THEN** AppSpec 在执行命令前拒绝该配置

### Requirement: custom App SHALL 获得标准构建路径环境

AppBuilder MUST 向 custom 命令提供当前工程的 build root、App 工作目录、App DEB 输出目录和目标 userspace 架构，路径 MUST
通过 `builder.paths` 计算。命令不得依赖调用方当前工作目录拼接旧顶层路径。

#### Scenario: 构建路径注入

- **WHEN** AppBuilder 构建 aarch64 custom App
- **THEN** 命令环境包含绝对的 `FLANGE_BUILD_ROOT`、`FLANGE_APP_WORK_DIR`、`FLANGE_APP_OUTPUT_DIR`
- **AND** `FLANGE_TARGET_ARCH` 为 `aarch64`

#### Scenario: AArch64 APT 架构映射

- **WHEN** aarch64 custom App 的 `build.apt_packages` 使用 `{arch}` 占位符
- **THEN** AppBuilder 向 APT 请求 Debian 架构名 `arm64`
- **AND** 传给构建命令的 `FLANGE_TARGET_ARCH` 仍为 flange 架构名 `aarch64`

