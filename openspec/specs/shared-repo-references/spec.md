# shared-repo-references Specification

## Purpose
TBD - created by archiving change add-shared-repo-references. Update Purpose after archive.
## Requirements
### Requirement: 命名仓库声明
配置中必须（SHALL）支持在顶层 `repos` 字典中声明命名仓库。每个命名仓库包含 `repo` URL、可选 `branch`/`commit`/`recurse_submodules` 等字段，语义与组件级仓库配置相同。

#### Scenario: 命名仓库配置存在
- **WHEN** 配置中声明 `repos.linux-a733` 包含 `repo` 和 `branch`
- **THEN** `SourceManager` 能够识别并按此配置 clone 仓库到 `.build/sources/repos/linux-a733/`

#### Scenario: 多个命名仓库并存
- **WHEN** 配置声明 `repos.linux-a733` 和 `repos.u-boot-aw2501` 两个命名仓库
- **THEN** 两者各自独立 clone 到 `.build/sources/repos/<name>/`，互不影响

### Requirement: 组件通过 from_repo 引用命名仓库
组件配置必须（SHALL）支持 `from_repo` 字段引用命名仓库，可选 `subpath` 字段指定仓库内子路径。当 `from_repo` 存在时，`SourceManager.ensure()` 返回对应命名仓库的子路径，不独立 clone。

#### Scenario: 组件引用命名仓库根
- **WHEN** 组件配置为 `{"from_repo": "u-boot-aw2501"}`（无 subpath）
- **THEN** `ensure()` 返回 `.build/sources/repos/u-boot-aw2501/`

#### Scenario: 组件引用命名仓库子路径
- **WHEN** 组件配置为 `{"from_repo": "linux-a733", "subpath": "src"}`
- **THEN** `ensure()` 返回 `.build/sources/repos/linux-a733/src/`

#### Scenario: 命名仓库只 clone 一次
- **WHEN** 多个组件（kernel、kernel_bsp、kernel_device）都声明 `from_repo: "linux-a733"`
- **THEN** `linux-a733` 仓库只 clone 一次，各组件返回该仓库的不同子路径

#### Scenario: 未声明的命名仓库引用报错
- **WHEN** 组件配置 `from_repo: "unknown-repo"` 但 `repos` 中没有此条目
- **THEN** `ensure()` 抛出明确错误，指出缺失的命名仓库名

### Requirement: 路径解析优先级
`SourceManager.ensure()` 必须（SHALL）按以下优先级解析组件源码路径：

1. `local_path` 优先级最高（开发本地路径）
2. `from_repo` + `subpath`（命名仓库子路径）
3. 传统 `repo` + 组件名独立 clone（fallback，保持原有行为）

#### Scenario: local_path 优先于 from_repo
- **WHEN** 组件同时声明 `local_path` 和 `from_repo`
- **THEN** `ensure()` 返回 `local_path`，不解析 `from_repo`

#### Scenario: from_repo 优先于独立 clone
- **WHEN** 组件同时声明 `from_repo` 和 `repo`
- **THEN** `ensure()` 使用 `from_repo` 路径，忽略 `repo`

#### Scenario: 无 from_repo 时走独立 clone
- **WHEN** 组件只声明 `repo` 字段（无 `from_repo` 无 `local_path`）
- **THEN** `ensure()` 按原有逻辑 clone 到 `.build/sources/<component>/<board>/`

### Requirement: 命名仓库存储位置隔离
命名仓库必须（SHALL）存储在 `.build/sources/repos/<name>/` 目录，不得与独立 clone 的 `.build/sources/<component>/<board>/` 混用。

#### Scenario: 命名仓库独立存储
- **WHEN** clone 命名仓库 `linux-a733`
- **THEN** 仓库位于 `.build/sources/repos/linux-a733/`，不位于 `.build/sources/kernel/` 下

#### Scenario: 独立 clone 组件保持原位置
- **WHEN** Rockchip kernel 组件使用传统 `repo` 配置
- **THEN** 仓库仍 clone 到 `.build/sources/kernel/<board>/`，不受命名仓库机制影响

