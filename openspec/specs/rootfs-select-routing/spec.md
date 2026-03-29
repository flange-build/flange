### Requirement: rootfs 顶层 alias + select() 路由
`rootfs/BUILD.bazel` SHALL 使用 alias + `select()` 按平台 `config_setting` 路由到 `rootfs/<platform>/` 子目录的具体实现。

#### Scenario: Rockchip 平台路由
- **WHEN** 使用 `--config=radxa-zero3w`（Rockchip 平台）构建 `//rootfs`
- **THEN** 实际构建 `//rootfs/rockchip` target

#### Scenario: 新增平台扩展
- **WHEN** 需要新增 Allwinner 平台的 rootfs 支持
- **THEN** 只需在 `rootfs/BUILD.bazel` 的 `select()` 中增加一行路由

### Requirement: rootfs module extension 注册源码仓库
`build/extensions.bzl` SHALL 包含 `rootfs_sources` module extension，从 board.bzl 配置中读取 rootfs tarball URL 和 sha256，注册 `rootfs_source` repository rule。

#### Scenario: module extension 注册
- **WHEN** `MODULE.bazel` 声明 `rootfs.source(board = "radxa-zero3w")`
- **THEN** 创建 `@rootfs_src_radxa_zero3w` 仓库，下载对应的 ubuntu-base tarball

### Requirement: rootfs 产物收集
rootfs 构建 SHALL 支持产物收集，将 `rootfs.tar.gz` 复制到 `target/<board>/rootfs/` 目录。

#### Scenario: 产物收集目标
- **WHEN** 查看 `rootfs/BUILD.bazel`
- **THEN** 包含 `rootfs_collect` 规则将产物复制到 target 目录
