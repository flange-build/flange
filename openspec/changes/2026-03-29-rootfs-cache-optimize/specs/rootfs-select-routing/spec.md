## MODIFIED Requirements

### Requirement: rootfs 顶层 alias + select() 路由
`rootfs/BUILD.bazel` SHALL 使用 alias + `select()` 按平台 `config_setting` 路由到 `rootfs/<platform>/` 子目录的 customize target。

#### Scenario: Rockchip 平台路由
- **WHEN** 使用 `--config=radxa-zero3w`（Rockchip 平台）构建 `//rootfs`
- **THEN** 实际构建 `//rootfs/rockchip` target（即 rootfs_customize 实例）

#### Scenario: 新增平台扩展
- **WHEN** 需要新增 Allwinner 平台的 rootfs 支持
- **THEN** 只需在 `rootfs/BUILD.bazel` 的 `select()` 中增加一行路由
