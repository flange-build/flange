## ADDED Requirements

### Requirement: rootfs_customize 框架 rule 定义
`build/rootfs_customize.bzl` SHALL 定义 `rootfs_customize` rule，负责在 base rootfs 基础上应用自定义 deb 包和 overlay，产出最终 `rootfs.tar.gz`。

#### Scenario: rootfs_customize rule 属性定义
- **WHEN** 查看 `rootfs_customize` rule 的属性
- **THEN** 包含以下必需属性：`base`（base-rootfs.tar.zst label）、`build_script`（平台构建脚本）

#### Scenario: rootfs_customize rule 可选属性
- **WHEN** 查看 `rootfs_customize` rule 的可选属性
- **THEN** 包含 `custom_packages`（自定义包名列表）、`custom_packages_dir`（自定义 deb 包目录 label）、`overlay`（board overlay label）、`arch`（目标架构）

### Requirement: rootfs_customize 环境变量契约
框架层 SHALL 通过环境变量向策略脚本传递构建参数：`ROOTFS_BASE`（base-rootfs.tar.zst 路径）、`ROOTFS_CUSTOM_PACKAGES`（空格分隔的自定义包组件名）、`ROOTFS_PACKAGES_DIR`（packages 目录路径）、`ROOTFS_OVERLAY_DIR`（overlay 目录路径）、`ROOTFS_ARCH`（目标架构）。策略脚本须设置 `ROOTFS_OUTPUT` 指向最终 rootfs.tar.gz 路径。

#### Scenario: 环境变量传递给策略脚本
- **WHEN** rootfs_customize rule 执行时
- **THEN** 策略脚本可通过 `ROOTFS_BASE`、`ROOTFS_CUSTOM_PACKAGES`、`ROOTFS_PACKAGES_DIR`、`ROOTFS_OVERLAY_DIR`、`ROOTFS_ARCH` 环境变量获取构建参数

#### Scenario: 策略脚本设置输出路径
- **WHEN** 策略脚本完成构建
- **THEN** `ROOTFS_OUTPUT` 变量指向生成的 `rootfs.tar.gz` 绝对路径

### Requirement: rootfs_customize 产出 rootfs.tar.gz
`rootfs_customize` rule SHALL 产出 `rootfs.tar.gz` 文件，由框架层在策略脚本执行后从 `ROOTFS_OUTPUT` 路径收集。

#### Scenario: 构建产出文件
- **WHEN** 执行 rootfs_customize 构建
- **THEN** 产出 `rootfs.tar.gz`

### Requirement: rootfs_customize 使用 no-sandbox 执行
rootfs customize 构建可能需要 chroot 安装自定义 deb 包，SHALL 使用 `no-sandbox` 和 `no-remote` 执行要求。

#### Scenario: 执行模式
- **WHEN** 查看 `rootfs_customize` rule 的 `execution_requirements`
- **THEN** 包含 `"no-sandbox": "1"` 和 `"no-remote": "1"`
