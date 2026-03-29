### Requirement: rootfs_base 框架 rule 定义
`build/rootfs_base.bzl` SHALL 定义 `rootfs_base` rule，负责从 ubuntu-base tarball 构建基础 rootfs（包含 apt 包安装），产出 `base-rootfs.tar.zst`。

#### Scenario: rootfs_base rule 属性定义
- **WHEN** 查看 `rootfs_base` rule 的属性
- **THEN** 包含以下必需属性：`rootfs_src`（tarball label）、`build_script`（平台构建脚本）、`packages`（apt 包列表）

#### Scenario: rootfs_base rule 可选属性
- **WHEN** 查看 `rootfs_base` rule 的可选属性
- **THEN** 包含 `arch`（目标架构，默认 arm64）、`jobs`（并行任务数）

### Requirement: rootfs_base 环境变量契约
框架层 SHALL 通过环境变量向策略脚本传递构建参数：`ROOTFS_TARBALL`（tarball 路径）、`ROOTFS_PACKAGES`（空格分隔的 apt 包列表）、`ROOTFS_APT_CACHE_DIR`（APT 下载缓存目录路径）、`ROOTFS_ARCH`（目标架构）。策略脚本须设置 `ROOTFS_BASE_OUTPUT` 指向最终 base-rootfs.tar.zst 路径。

#### Scenario: 环境变量传递给策略脚本
- **WHEN** rootfs_base rule 执行时
- **THEN** 策略脚本可通过 `ROOTFS_TARBALL`、`ROOTFS_PACKAGES`、`ROOTFS_APT_CACHE_DIR`、`ROOTFS_ARCH` 环境变量获取构建参数

#### Scenario: 策略脚本设置输出路径
- **WHEN** 策略脚本完成构建
- **THEN** `ROOTFS_BASE_OUTPUT` 变量指向生成的 `base-rootfs.tar.zst` 绝对路径

### Requirement: rootfs_base 产出 base-rootfs.tar.zst
`rootfs_base` rule SHALL 产出 `base-rootfs.tar.zst` 文件（zstd 压缩），由框架层在策略脚本执行后从 `ROOTFS_BASE_OUTPUT` 路径收集。

#### Scenario: 构建产出文件
- **WHEN** 执行 rootfs_base 构建
- **THEN** 产出 `base-rootfs.tar.zst`（zstd 压缩格式）

### Requirement: rootfs_base 使用 no-sandbox 执行
rootfs base 构建需要 chroot 和 mount 操作，SHALL 使用 `no-sandbox` 和 `no-remote` 执行要求。

#### Scenario: 执行模式
- **WHEN** 查看 `rootfs_base` rule 的 `execution_requirements`
- **THEN** 包含 `"no-sandbox": "1"` 和 `"no-remote": "1"`
