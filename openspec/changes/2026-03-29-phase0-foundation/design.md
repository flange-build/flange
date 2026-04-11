> **归档说明**：本设计方案属于 Bazel 构建系统时代（v1.0），仅作历史参考。当前架构参见 `openspec/flange-build-tool-design.md`。

## Context

flange 项目已完成详细的架构设计文档（build-system-design.md、app-architecture.md），但尚无任何可执行代码。本阶段（Phase 0）是自底向上实施路径的第一步，搭建 Docker 容器化构建环境和 Bazel 项目骨架，为后续所有阶段提供基础设施。

首个目标平台为 Rockchip RK3566（Radxa Zero 3W），构建环境需要预装 aarch64 交叉编译工具链。

## Goals / Non-Goals

**Goals:**
- 提供可复现的 Docker 构建容器，内含 Bazel 8.x 和 aarch64-linux-gnu 工具链
- 建立 Bazel 项目骨架（MODULE.bazel、BUILD.bazel、.bazelrc）
- 配置 Docker volume 持久化 Bazel 缓存，避免每次构建重新下载
- 验证标准：在容器内执行 `bazel version` 成功

**Non-Goals:**
- 不注册 Bazel cc_toolchain（阶段 1 的工作）
- 不实现配置解析引擎或 platform/board 配置
- 不实现任何组件构建规则
- 不实现 envsetup.sh CLI 脚手架

## Decisions

### D1: Bazel 安装方式——使用 bazelisk

通过 bazelisk 管理 Bazel 版本，在项目根目录放置 `.bazelversion` 文件锁定版本号。

**为什么不直接安装 Bazel？** bazelisk 是 Bazel 官方推荐的版本管理器，团队成员和 CI 环境自动使用同一版本，避免版本不一致问题。

### D2: Docker 镜像架构——单阶段构建

构建容器使用单阶段 Dockerfile，基于 `ubuntu:24.04`。不使用多阶段构建，因为构建容器本身就是开发环境，不需要优化镜像体积。

### D3: Bazel output base 持久化路径

Bazel output base 通过 Docker volume 映射到宿主机 `output/bazel/`，与设计文档一致。`.bazelrc` 中通过 `startup --output_base` 指定。

**为什么不用默认路径？** 默认路径在容器 home 目录下，容器重建后丢失。映射到项目目录下的 `output/bazel/` 可在容器重建后保留缓存。

### D4: Docker Compose 而非裸 docker run

使用 `docker-compose.yml` 管理构建服务，简化 volume 映射和环境变量配置。用户后续通过 `flange` CLI 间接调用，不需要手动执行 docker compose 命令。

### D5: .gitignore 策略

忽略以下内容：
- `output/`、`target/` — 构建产物
- `.flange/` — 运行时状态
- `bazel-*` — Bazel 符号链接
- Docker 运行时文件

## Risks / Trade-offs

- **[风险] Bazel 8.x 兼容性**：Bazel 8 较新，部分第三方规则可能尚未适配 → 缓解：Phase 0 不引入第三方规则，仅验证 Bazel 基础功能
- **[风险] Docker 在 macOS 上的性能**：volume mount 在 macOS Docker 上较慢 → 缓解：后续可考虑使用 `:cached` 或 VirtioFS（Docker Desktop 默认已启用）
- **[取舍] 交叉编译工具链预装 vs 按需安装**：预装在 Docker 镜像中增大镜像体积（约 200MB），但避免每次容器启动都安装 → 选择预装，构建速度优先