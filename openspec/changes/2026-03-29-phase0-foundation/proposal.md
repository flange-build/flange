> **归档说明**：本变更方案属于 Bazel 构建系统时代（v1.0）。flange 已于 2026-04 迁移至 Python 统一架构（v2.0），本方案中涉及 Bazel/Starlark/BUILD.bazel 的实现细节仅作历史参考。

## Why

flange 项目目前仅有设计文档，尚无任何可执行代码。要启动自底向上的实施路径，首先需要搭建构建基础设施——Docker 容器化构建环境和 Bazel 项目骨架。这是所有后续阶段（交叉编译、配置体系、组件构建）的前提条件。

## What Changes

- 新增 `docker/Dockerfile`：基于 ubuntu:24.04，安装 Bazel 8.x 和 aarch64-linux-gnu 交叉编译工具链
- 新增 `docker-compose.yml`：定义构建服务，配置项目目录挂载和 Bazel 缓存持久化
- 新增 `MODULE.bazel`：Bazel 8 模块定义，声明项目名称和外部依赖
- 新增顶层 `BUILD.bazel`：项目根目录构建目标
- 新增 `.bazelrc`：Bazel 运行配置，包含 output base 路径和基本构建选项
- 新增 `.gitignore`：忽略构建产物、Docker 运行时状态、Bazel 输出等

## 非目标

- 本阶段不实现交叉编译工具链的 Bazel toolchain 注册（阶段 1）
- 本阶段不实现配置体系（registry.bzl、deep_merge 等）
- 本阶段不实现任何组件（kernel、bootloader、rootfs、image）的构建规则
- 本阶段不实现 CLI 脚手架（envsetup.sh）

## Capabilities

### New Capabilities
- `docker-build-env`：Docker 容器化构建环境，提供一致的编译环境和工具链
- `bazel-project-skeleton`：Bazel 项目骨架，包含模块定义、构建配置和基本目录结构

### Modified Capabilities

（无）

## Impact

- 新增文件：`docker/Dockerfile`、`docker-compose.yml`、`MODULE.bazel`、`BUILD.bazel`、`.bazelrc`、`.gitignore`
- 依赖引入：Bazel 8.x（通过 bazelisk 管理）、Docker / Docker Compose
- 验证标准：`docker compose run build bazel version` 成功输出 Bazel 版本号