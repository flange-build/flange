## ADDED Requirements

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
