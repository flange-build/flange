## Context

Phase 3/4 已完成内核和 bootloader 的构建框架，确立了"框架+策略脚本"架构模式。现在需要构建根文件系统，基于 ubuntu-base tarball 通过 qemu-user-static chroot 安装包、应用 overlay、安装自定义 deb 包，产出 `rootfs.tar.gz`。

当前已有基础设施：
- 三层配置体系（platform → SoC → board）+ `config_registry`
- 框架+策略脚本模式（`kernel_build.bzl`、`bootloader_build.bzl` 可参考）
- Module extension 驱动的源码仓库注册
- `board/radxa-zero3w/board.bzl` 已有 `rootfs: {base: "noble"}`
- `board/radxa-zero3w/BUILD.bazel` 已有 overlay filegroup

## Goals / Non-Goals

**Goals:**
- `bazel build //rootfs --config=radxa-zero3w` 产出 `rootfs.tar.gz`
- 支持 apt 包安装（包列表由 board.bzl 声明）
- 支持自定义 deb 包选择性安装（组件化目录结构 + board.bzl 配置）
- 支持 board overlay 文件覆盖
- rootfs 按平台分子目录，与 kernel/bootloader 统一模式

**Non-Goals:**
- 不生成 ext4 镜像（留给 Phase 6）
- 不实现 pre/post hook 机制
- 不支持 debootstrap 全量安装模式
- 不处理内核模块安装到 rootfs（Phase 6 镜像打包时处理）

## Decisions

### 1. rootfs 按平台分子目录

**选择**: rootfs 与 kernel/bootloader 统一，按平台建子目录

**替代方案**: 规范原定 rootfs 保持扁平结构

**理由**: 不同平台的 rootfs 构建可能有差异化处理（Rockchip 固件安装、GPU 驱动配置等），按平台分目录允许各平台有独立的 build.sh 策略脚本。统一模式也降低认知负担。

### 2. ubuntu-base tarball 通过 HTTP 下载

**选择**: `rootfs_source.bzl` 使用 `ctx.download()` 从 Ubuntu 官方 CDN 下载 tarball

**替代方案**: 使用 Bazel 内置 `http_archive` 或 git clone

**理由**: ubuntu-base 是固定版本的 tarball，不是 git 仓库。`ctx.download()` 直接、简单，支持 sha256 校验。完整 URL 在 board.bzl 中声明，sha256 可选。

### 3. qemu-user-static 预装到 Docker 镜像

**选择**: Dockerfile 中安装 `qemu-user-static` 包

**替代方案**: 依赖宿主机 binfmt_misc 注册

**理由**: 预装到镜像使构建环境自包含，不要求宿主机额外配置。Docker 容器需以 privileged 模式运行或挂载 binfmt_misc。

### 4. 自定义 deb 包通过环境变量传递包名

**选择**: 框架层将 `packages/` 整个目录作为输入传入，board.bzl 中的 `custom_packages` 列表通过环境变量 `ROOTFS_CUSTOM_PACKAGES` 传给 build.sh，build.sh 运行时按包名在目录中查找对应子目录

**替代方案**: 在 BUILD.bazel 中用 select() 逐一引用 `//packages/<name>` label

**理由**: Starlark 无法根据配置值动态生成 label 列表。方案 B 避免了在 board.bzl 和 BUILD.bazel 两处维护配置，实现"改一处配置"的原则。

### 5. 包列表在 board.bzl 中声明

**选择**: apt 包列表直接写在 board.bzl 的 `rootfs.packages` 数组中

**替代方案**: 单独的 packages.txt 文件

**理由**: 与内核/bootloader 配置风格一致，所有板级构建参数集中在 board.bzl。包列表通常不会太长，放在 .bzl 文件中可读性足够。

## Risks / Trade-offs

**[chroot 需要 root 权限]** → Bazel 使用 `no-sandbox` 执行，Docker 容器以 root 运行。注意不要在 chroot 环境中破坏宿主文件系统。build.sh 中严格使用绝对路径。

**[qemu-user-static 性能]** → 跨架构 chroot 中 apt install 较慢。可接受，因为 rootfs 构建频率低于内核编译。Bazel 缓存可避免重复构建。

**[自定义 deb 包的粗粒度依赖追踪]** → 整个 `packages/` 目录作为输入，任何子目录变更都会触发重建。可接受，因为自定义包数量有限。

**[ubuntu-base CDN 可用性]** → 依赖外部网络下载 tarball。Bazel 的 repository rule 会缓存下载结果，首次下载后不再重复。

## Open Questions

- rootfs 构建是否需要 `--privileged` Docker 标志？还是 `SYS_CHROOT` capability 就够？实施时验证。
