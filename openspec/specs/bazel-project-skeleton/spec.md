# bazel-project-skeleton Specification

## Purpose
TBD - created by archiving change 2026-03-29-phase0-foundation. Update Purpose after archive.
## Requirements
### Requirement: MODULE.bazel 定义项目模块
项目根目录 SHALL 包含 `MODULE.bazel` 文件，声明项目名称为 `flange`。

#### Scenario: MODULE.bazel 存在且合法
- **WHEN** 在构建容器内执行 `bazel mod graph`
- **THEN** 输出包含 `flange` 模块名称，无语法错误

### Requirement: 顶层 BUILD.bazel 存在
项目根目录 SHALL 包含 `BUILD.bazel` 文件，作为 Bazel workspace 的根 package。

#### Scenario: 顶层 BUILD.bazel 可被 Bazel 解析
- **WHEN** 在构建容器内执行 `bazel query //...`
- **THEN** 命令成功执行，不报告 BUILD 文件缺失错误

### Requirement: .bazelrc 配置 output base
`.bazelrc` SHALL 通过 `startup --output_base` 将 Bazel output base 指向 `/workspace/output/bazel`（容器内路径），对应宿主机的 `output/bazel/` 目录。

#### Scenario: Bazel output base 路径正确
- **WHEN** 在构建容器内执行 `bazel info output_base`
- **THEN** 输出路径为 `/workspace/output/bazel`

### Requirement: .gitignore 忽略构建产物
项目 SHALL 包含 `.gitignore` 文件，忽略 `output/`、`target/`、`.flange/`、`bazel-*` 等构建产物和运行时状态。

#### Scenario: 构建产物不入库
- **WHEN** 执行 `bazel build` 后运行 `git status`
- **THEN** `output/` 和 `bazel-*` 目录不出现在未跟踪文件列表中

### Requirement: .bazelversion 锁定 Bazel 版本
项目根目录 SHALL 包含 `.bazelversion` 文件，锁定 Bazel 8.x 系列的具体版本号，供 bazelisk 使用。

#### Scenario: .bazelversion 内容为具体版本号
- **WHEN** 查看 `.bazelversion` 文件内容
- **THEN** 内容为形如 `8.x.y` 的具体版本号（如 `8.2.1`）

