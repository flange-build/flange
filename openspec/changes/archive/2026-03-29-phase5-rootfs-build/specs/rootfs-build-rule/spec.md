## ADDED Requirements

### Requirement: rootfs_build 框架 rule 定义
`build/rootfs_build.bzl` SHALL 定义 `rootfs_build` rule，遵循框架+策略脚本架构。框架负责源码管理、环境变量设置和产物收集，平台策略脚本负责实际构建逻辑。

#### Scenario: rootfs_build rule 属性定义
- **WHEN** 查看 `rootfs_build` rule 的属性
- **THEN** 包含以下必需属性：`rootfs_src`（tarball label）、`build_script`（平台构建脚本）、`packages`（apt 包列表）、`overlay`（board overlay label）

#### Scenario: rootfs_build rule 可选属性
- **WHEN** 查看 `rootfs_build` rule 的可选属性
- **THEN** 包含 `custom_packages_dir`（自定义 deb 包目录 label）、`custom_packages`（自定义包名列表）、`jobs`（并行任务数）

### Requirement: rootfs_build 环境变量契约
框架层 SHALL 通过环境变量向策略脚本传递构建参数：`ROOTFS_TARBALL`（tarball 路径）、`ROOTFS_PACKAGES`（空格分隔的 apt 包列表）、`ROOTFS_OVERLAY_DIR`（overlay 目录路径）、`ROOTFS_CUSTOM_PACKAGES`（空格分隔的自定义包组件名）、`ROOTFS_PACKAGES_DIR`（packages 目录路径）、`ROOTFS_ARCH`（目标架构）。策略脚本须设置 `ROOTFS_OUTPUT` 指向最终 rootfs.tar.gz 路径。

#### Scenario: 环境变量传递给策略脚本
- **WHEN** rootfs_build rule 执行时
- **THEN** 策略脚本可通过 `ROOTFS_TARBALL`、`ROOTFS_PACKAGES`、`ROOTFS_OVERLAY_DIR` 等环境变量获取构建参数

#### Scenario: 策略脚本设置输出路径
- **WHEN** 策略脚本完成构建
- **THEN** `ROOTFS_OUTPUT` 变量指向生成的 `rootfs.tar.gz` 绝对路径

### Requirement: rootfs_build 产出 rootfs.tar.gz
`rootfs_build` rule SHALL 产出 `rootfs.tar.gz` 文件，由框架层在策略脚本执行后从 `ROOTFS_OUTPUT` 路径收集。

#### Scenario: 构建产出文件
- **WHEN** 执行 `bazel build //rootfs --config=radxa-zero3w`
- **THEN** 产出 `rootfs.tar.gz`

### Requirement: rootfs_build 使用 no-sandbox 执行
rootfs 构建需要 chroot 和包管理操作，SHALL 使用 `no-sandbox` 和 `no-remote` 执行要求。

#### Scenario: 执行模式
- **WHEN** 查看 `rootfs_build` rule 的 `execution_requirements`
- **THEN** 包含 `"no-sandbox": "1"` 和 `"no-remote": "1"`

### Requirement: rootfs_source repository rule
`build/rootfs_source.bzl` SHALL 定义 `rootfs_source` repository rule，通过 HTTP 下载 ubuntu-base tarball。接受 `url`（必需）和 `sha256`（可选）属性。

#### Scenario: 下载 ubuntu-base tarball
- **WHEN** Bazel 解析 `rootfs_source` repository rule
- **THEN** 从指定 URL 下载 tarball 并缓存

#### Scenario: sha256 可选校验
- **WHEN** `rootfs_source` 未指定 `sha256` 属性
- **THEN** 仍可正常下载（但会输出警告建议提供 sha256）
