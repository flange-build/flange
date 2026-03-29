## ADDED Requirements

### Requirement: 自定义 deb 包目录结构
`packages/` 目录 SHALL 按软件组件组织，每个组件一个子目录，子目录内包含该组件的一个或多个 `.deb` 文件。

#### Scenario: 目录结构
- **WHEN** 查看 `packages/` 目录
- **THEN** 每个子目录代表一个软件组件（如 `gpu-driver/`、`wifi-firmware/`），子目录内包含 `.deb` 文件

#### Scenario: 组件目录包含 BUILD.bazel
- **WHEN** 查看任一组件子目录
- **THEN** 不需要独立的 BUILD.bazel，整个 `packages/` 目录由顶层 `packages/BUILD.bazel` 统一导出

### Requirement: packages 目录统一 filegroup 导出
`packages/BUILD.bazel` SHALL 通过 `filegroup` 导出整个目录下所有 `.deb` 文件，供 `rootfs_build` rule 引用。

#### Scenario: filegroup 导出
- **WHEN** 查看 `packages/BUILD.bazel`
- **THEN** 包含 `filegroup` 使用 `glob(["**/*.deb"])` 导出所有 deb 文件

### Requirement: 自定义包通过 board.bzl 配置安装策略
board.bzl 的 `rootfs.custom_packages` 字段 SHALL 声明需要安装的组件名列表，对应 `packages/` 下的子目录名。未列入的组件不会被安装。

#### Scenario: 配置安装策略
- **WHEN** board.bzl 中 `rootfs.custom_packages = ["gpu-driver", "wifi-firmware"]`
- **THEN** rootfs 构建时只安装 `packages/gpu-driver/` 和 `packages/wifi-firmware/` 中的 deb 包

#### Scenario: 空列表不安装自定义包
- **WHEN** board.bzl 中 `rootfs.custom_packages` 为空列表或未声明
- **THEN** rootfs 构建时跳过自定义 deb 包安装
