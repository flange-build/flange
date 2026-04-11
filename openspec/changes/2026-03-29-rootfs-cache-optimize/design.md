> **归档说明**：本设计方案属于 Bazel 构建系统时代（v1.0），仅作历史参考。当前架构参见 `openspec/flange-build-tool-design.md`。

## Context

当前 `rootfs_build` 是一个单体 Bazel rule，将 ubuntu-base 解压、apt 包安装、自定义 deb 安装、overlay 应用、打包全部耦合在一个 action 中。由于使用 qemu-user-static 模拟执行，apt install 阶段耗时 ~38 分钟。Bazel 的 action cache 在所有输入不变时可以跳过，但任何输入变化（即使只改了 overlay 文件）都会触发完整重建。

参考 Armbian 的两阶段缓存架构，核心思路是将 rootfs 构建拆分为"基础系统构建"和"定制化"两步，按变化频率分离。

## Goals / Non-Goals

**Goals:**
- 改 overlay 或自定义 deb 时，rootfs 重建时间从 ~38 分钟降至 ~1-2 分钟
- 即使 base rootfs cache miss（包列表变化），通过 APT 下载缓存减少网络下载时间
- 保持 `bazel build //rootfs --config=radxa-zero3w` 对外接口不变

**Non-Goals:**
- 不实现跨机器远程缓存（OCI registry）
- 不实现 apt-cacher-ng 代理
- 不改变 board.bzl 配置结构

## Decisions

### Decision 1: 拆分为 rootfs_base + rootfs_customize 两个 Bazel rule

将原 `rootfs_build` 拆分为两个独立 rule，形成 Bazel 依赖链：

```
rootfs_base                     rootfs_customize
(tarball + packages)            (base + custom_debs + overlay)
        │                               │
        ▼                               ▼
  base-rootfs.tar.zst             rootfs.tar.gz
```

**为什么不在 build.sh 内部做缓存（方案 A/C）：** Bazel 的核心契约是"相同输入 → 相同输出"。在 action 内部引入 Bazel 不可见的缓存目录会破坏这个契约，导致不可预测的构建行为。拆 rule 是 Bazel 原生的依赖追踪方式。

**rootfs_base rule（`build/rootfs_base.bzl`）：**
- 输入：ubuntu-base tarball、apt 包列表、平台 build_base.sh 脚本
- 输出：`base-rootfs.tar.zst`
- 执行：解压 tarball → qemu 设置 → chroot apt install → 清理 → zstd 打包
- 执行要求：`no-sandbox`、`no-remote`（需要 chroot + mount）

**rootfs_customize rule（`build/rootfs_customize.bzl`）：**
- 输入：base-rootfs.tar.zst、自定义 deb 文件、overlay 文件、平台 build_customize.sh 脚本
- 输出：`rootfs.tar.gz`
- 执行：解压 base → 自定义 deb 安装（如有则 chroot dpkg）→ overlay 复制 → 打包
- 执行要求：`no-sandbox`、`no-remote`

### Decision 2: APT 下载缓存通过 Docker volume 持久化

在 `docker-compose.yml` 中新增 volume 挂载：
```yaml
volumes:
  - ./cache/apt:/cache/apt
```

`build_base.sh` 在 chroot 前将 `/cache/apt` bind-mount 到 chroot 的 `/var/cache/apt/archives/`，apt-get install 命中已下载的 .deb 文件。构建完成后 unmount。

**为什么选择 bind-mount 而不是复制：** bind-mount 是零拷贝的，且 apt 安装后新下载的 .deb 自动持久化到宿主机缓存目录。

### Decision 3: base rootfs 使用 zstd 压缩

base-rootfs 产物使用 `zstdmt -5` 压缩（多线程 zstd，压缩比 5）：
- zstd 解压速度比 gzip 快 3-5x，customize 步骤解压 base 更快
- 多线程压缩充分利用多核 CPU
- 压缩比 5 是速度和大小的平衡点（Armbian 默认也是 5）

最终产出 `rootfs.tar.gz` 仍用 gzip，保持与下游工具的兼容性。

### Decision 4: 平台构建脚本拆分

将 `rootfs/rockchip/build.sh` 拆分为：

- `build_base.sh`：接收 `ROOTFS_TARBALL`、`ROOTFS_PACKAGES`、`ROOTFS_APT_CACHE_DIR`、`ROOTFS_ARCH` 环境变量。负责解压 tarball → qemu → mount → apt install → 清理 → zstd 打包。设置 `ROOTFS_BASE_OUTPUT` 指向产出路径。

- `build_customize.sh`：接收 `ROOTFS_BASE`、`ROOTFS_CUSTOM_PACKAGES`、`ROOTFS_PACKAGES_DIR`、`ROOTFS_OVERLAY_DIR` 环境变量。负责解压 base → 自定义 deb 安装 → overlay → gzip 打包。设置 `ROOTFS_OUTPUT` 指向产出路径。

### Decision 5: rootfs/rockchip/BUILD.bazel 实例化两个 rule

```
rootfs_base(
    name = "base",
    rootfs_src = select({...}),
    packages = select({...}),
    build_script = "build_base.sh",
)

rootfs_customize(
    name = "rockchip",  # 保持原 target 名，select() 路由不变
    base = ":base",
    custom_packages = select({...}),
    custom_packages_dir = "//packages:all_debs",
    overlay = select({...}),
    build_script = "build_customize.sh",
)
```

顶层 `//rootfs` alias 仍路由到 `//rootfs/rockchip`（即 customize target），无需改动。

## Risks / Trade-offs

- **两个 rule 都需要 privileged 模式** → customize 阶段如果有自定义 deb 也需要 chroot + dpkg。如果没有自定义 deb，customize 只做 overlay 复制和 tar 打包，不需要 chroot。当前设计统一用 `no-sandbox`，不做条件判断。

- **APT 缓存目录可能膨胀** → 不自动清理，用户可手动 `rm -rf cache/apt/` 释放。不做自动过期机制，避免复杂性。

- **base-rootfs.tar.zst 依赖 zstd 工具** → Dockerfile 必须预装 zstd 包，否则 build_customize.sh 无法解压 base。

- **原 rootfs_build.bzl 和 build.sh 移除** → 破坏性变更，但仅影响内部构建规则，不影响用户命令。