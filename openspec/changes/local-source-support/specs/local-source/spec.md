## ADDED Requirements

### Requirement: board 配置支持 local_path 字段

board 配置的 `kernel` 和 `bootloader` 字典 SHALL 支持可选的 `local_path` 字段。当 `local_path` 为非空字符串时，构建系统 MUST 使用该本地路径作为源码来源；当 `local_path` 为空字符串或未设置时，MUST 使用 `repo` + `branch` 从远程 git 仓库获取源码。

#### Scenario: 设置 local_path 启用本地模式
- **WHEN** board.bzl 的 kernel 配置中 `local_path` 设为 `"/home/user/kernel"`
- **THEN** 构建系统使用 `/home/user/kernel` 作为内核源码目录，不执行 git clone

#### Scenario: local_path 为空使用远程模式
- **WHEN** board.bzl 的 kernel 配置中 `local_path` 为 `""` 或未设置
- **THEN** 构建系统从 `repo` 指定的远程 git 仓库浅克隆源码（现有行为不变）

#### Scenario: bootloader 同样支持 local_path
- **WHEN** board.bzl 的 bootloader 配置中 `local_path` 设为非空路径
- **THEN** 构建系统使用该路径作为 U-Boot 源码目录

### Requirement: 本地模式使用 symlink 挂载源码

repository rule 在本地模式下 MUST 使用 `ctx.symlink()` 将源码目录 symlink 到 external 仓库的 `src/` 路径下，而非复制文件。

#### Scenario: symlink 创建
- **WHEN** `local_path` 为 `/home/user/kernel`
- **THEN** 外部仓库中 `src/` 为指向 `/home/user/kernel` 的 symlink

#### Scenario: 本地路径不存在时报错
- **WHEN** `local_path` 指向一个不存在的目录
- **THEN** repository rule MUST 以明确的错误信息失败，提示路径不存在

### Requirement: 基于 .git/index 的变更检测

本地模式下，repository rule MUST 使用 `ctx.watch()` 监控本地源码目录的 `.git/index` 文件。当该文件变更时（如执行 `git add`），Bazel MUST 自动重新 fetch 该 repository，从而触发下游构建 action 重新执行。

#### Scenario: git add 后自动触发重建
- **WHEN** 用户修改了本地内核源码并执行 `git add`
- **THEN** `.git/index` 变更，Bazel 自动 re-fetch repository，下游 kernel_build action 重新执行

#### Scenario: touch .git/index 手动触发重建
- **WHEN** 用户修改了文件但不想执行 `git add`，改为执行 `touch <local_path>/.git/index`
- **THEN** Bazel 同样检测到变更，触发 re-fetch 和重建

### Requirement: .fetch_stamp 保证下游 action 重跑

本地模式下，repository rule MUST 在每次 fetch 时生成 `.fetch_stamp` 文件（内容为当前时间戳），并将其纳入导出的 filegroup srcs。该文件确保即使 `src/Makefile` 内容不变，下游 build action 也能检测到输入变更并重新执行。

#### Scenario: re-fetch 后 .fetch_stamp 内容变化
- **WHEN** repository rule 被重新 fetch
- **THEN** `.fetch_stamp` 内容更新为新的时间戳，Bazel 重新执行依赖此 filegroup 的 build action

### Requirement: 本地模式跳过源码重置和补丁

本地模式下，build rule 生成的构建脚本 MUST 跳过 `git reset --hard HEAD` 和所有补丁应用步骤，直接使用本地源码树的当前状态进行构建。

#### Scenario: 本地模式不执行 git reset
- **WHEN** 检测到 `.local_mode` 标记文件存在
- **THEN** 构建脚本跳过 `git reset --hard HEAD`，不修改本地源码树

#### Scenario: 本地模式不应用补丁
- **WHEN** 检测到 `.local_mode` 标记文件存在
- **THEN** 构建脚本跳过所有 `git apply` / `patch` 命令

#### Scenario: 远程模式保持现有行为
- **WHEN** `.local_mode` 标记文件不存在
- **THEN** 构建脚本执行 `git reset --hard HEAD` 并应用所有补丁（现有行为不变）

### Requirement: 本地模式支持 make 增量编译

本地模式下的构建 MUST 保留 `make` 自身的增量编译能力。构建脚本不得执行 `make clean` 或其他会清除已有编译产物的操作。

#### Scenario: 增量编译
- **WHEN** 用户修改了一个 `.c` 文件并触发重建
- **THEN** `make` 仅重新编译被修改的文件及其依赖，不执行全量编译
