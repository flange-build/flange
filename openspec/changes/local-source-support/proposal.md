> **归档说明**：本变更方案属于 Bazel 构建系统时代（v1.0）。flange 已于 2026-04 迁移至 Python 统一架构（v2.0），本方案中涉及 Bazel/Starlark/BUILD.bazel 的实现细节仅作历史参考。

## Why

当前 kernel 和 bootloader 源码仅支持从远程 git 仓库浅克隆获取。开发者在本地修改内核或 U-Boot 源码后，必须先推送到远程仓库，再触发构建，迭代效率低。需要支持直接指向本地源码目录，实现"改代码 → 构建 → 验证"的快速闭环。

## What Changes

- 在 board 配置中为 `kernel` 和 `bootloader` 增加可选的 `local_path` 字段
- repository rule 层支持双模式：`local_path` 非空时 symlink 到本地目录，否则走现有 git clone 流程
- 本地模式下通过 `ctx.watch(.git/index)` + `.fetch_stamp` 实现变更检测与增量重建
- 本地模式下构建脚本跳过 `git reset --hard` 和补丁应用，直接使用本地源码树的当前状态
- 本地模式下仍依赖 `make` 自身的增量编译能力

## 非目标

- 不涉及 rootfs（tarball 下载）和 rkbin（预编译固件）的本地路径支持
- 不实现文件级别的变更检测（使用 `git add` 粒度即可）
- 不改变远程模式的任何行为

## Capabilities

### New Capabilities

- `local-source`: 支持 kernel 和 bootloader 使用本地路径作为源码来源，包括 symlink 挂载、变更检测、本地模式构建行为

### Modified Capabilities

（无现有 spec 需要修改）

## Impact

- `board/*/board.bzl` — 所有板级配置文件的 kernel/bootloader 字段结构变更（新增可选字段，向后兼容）
- `build/kernel_source.bzl` — repository rule 新增本地模式分支
- `build/bootloader_source.bzl` — 同上
- `build/extensions.bzl` — 传递 `local_path` 参数
- `build/kernel_build.bzl` — 构建脚本检测本地模式，跳过 reset 和补丁
- `build/bootloader_build.bzl` — 同上
- `docker-compose.yml` — 本地源码目录需挂载到容器内（如宿主机路径 → `/workspace/local/xxx`）

## 注意事项

- `local_path` 填写的是**容器内路径**，不是宿主机路径；宿主机目录需在 `docker-compose.yml` 中映射
- macOS 默认文件系统大小写不敏感，内核源码存在大小写冲突文件（netfilter 等），如涉及相关模块需使用大小写敏感的 APFS 卷