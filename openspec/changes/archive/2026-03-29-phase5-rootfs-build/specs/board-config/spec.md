## MODIFIED Requirements

### Requirement: 板级配置声明 rootfs 基线版本
板级配置 dict SHALL 包含 `rootfs` 字段，声明根文件系统的完整构建参数：`url`（ubuntu-base tarball 完整下载地址）、`packages`（apt 包列表）、`custom_packages`（自定义 deb 包组件名列表，可选）。`sha256` 为可选字段，用于 tarball 完整性校验。

#### Scenario: radxa-zero3w rootfs 配置
- **WHEN** 查看 `board/radxa-zero3w/board.bzl` 中的 `rootfs` 配置
- **THEN** 包含 `url`（ubuntu-base tarball 地址）、`packages`（apt 包名列表）

#### Scenario: 自定义包配置
- **WHEN** 板子需要安装自定义 deb 包
- **THEN** `rootfs.custom_packages` 列表中包含对应的组件目录名（如 `["gpu-driver"]`）

#### Scenario: sha256 可选
- **WHEN** 板级配置未声明 `rootfs.sha256`
- **THEN** 构建仍可正常执行（但建议提供以确保可重复构建）
