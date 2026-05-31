# image-select-routing Specification

## Purpose
TBD - created by archiving change 2026-03-29-phase6-image-flash. Update Purpose after archive.
## Requirements
### Requirement: image 顶层 alias + select() 路由
`image/BUILD.bazel` SHALL 使用 alias + `select()` 按平台 `config_setting` 路由到 `image/<platform>/` 子目录的具体实现。

#### Scenario: Rockchip 平台路由
- **WHEN** 使用 `--config=radxa-zero3w`（Rockchip 平台）构建 `//image`
- **THEN** 实际构建 `//image/rockchip` target

#### Scenario: 新增平台扩展
- **WHEN** 需要新增 Allwinner 平台的镜像支持
- **THEN** 只需在 `image/BUILD.bazel` 的 `select()` 中新增一个条件分支，指向 `//image/allwinner`

### Requirement: image collect 路由
`image/BUILD.bazel` SHALL 提供 `collect` target，通过 alias + `select()` 路由到平台对应的 `image_collect` 实例。

#### Scenario: 收集 Rockchip 平台产物
- **WHEN** 执行 `bazel run //image:collect --config=radxa-zero3w`
- **THEN** 实际执行 `//image/rockchip:collect`

