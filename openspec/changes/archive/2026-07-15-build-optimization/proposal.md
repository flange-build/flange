## Why

flange 的增量构建系统存在两个效率和正确性问题：

1. **rootfs 无阶段缓存**：当前 `RockchipRootfsBuilder` 将 Phase 1（解压 tarball + apt install）和 Phase 2（overlay + custom debs）作为一个整体构建。cache.py 用单个哈希判断整个 rootfs 是否需要重建。结果是：改一行 overlay 文件或更新一个 App → 重走全部 `apt-get install`（5-15 分钟），而这些包根本没变。这是最大的构建时间浪费。

2. **App 源码哈希不完整**：`cache.py` 的 `_hash_app_sources()` 只 hash 了 `app.yaml` 文件内容和 `custom_packages` 列表。App 的实际源代码文件（bin/、conf/、scripts/、src/ 等）改变后 app.yaml 不变 → 缓存误命中 → 不重建。这是一个正确性 bug。

## What Changes

### 1. Rootfs 两阶段独立缓存

将 rootfs 构建拆为两个独立的缓存单元：

**Phase 1 — Base Rootfs**

哈希输入：
- `rootfs.url`（base tarball 地址）
- `rootfs.packages`（apt 安装的包列表，排序后）
- `arch`

缓存产物：`target/<board>/<product>/<variant>/rootfs/base.tar.gz`

行为：
- 哈希命中 → 直接解压 `base.tar.gz`，跳过 tarball 解压和 apt install
- 哈希未命中 → 完整执行 Phase 1，完成后保存 `base.tar.gz` 快照

**Phase 2 — Customize**

哈希输入：
- Phase 1 的 base hash（级联依赖）
- `board/<board>/overlay/` 目录树的递归文件哈希
- `custom_packages` 列表
- 所有 App .deb 文件的哈希（来自 `target/.../app/*.deb`）

缓存产物：`target/<board>/<product>/<variant>/rootfs/rootfs.tar.gz`（最终产物）

行为：
- 哈希命中 → 跳过整个 rootfs 构建
- 哈希未命中但 base 命中 → 从 base.tar.gz 开始，只执行 Phase 2
- 都未命中 → 完整执行 Phase 1 + Phase 2

**典型场景收益**：

| 变更内容 | Phase 1 | Phase 2 | 节省时间 |
|----------|---------|---------|---------|
| 改 overlay 文件 | 跳过 (cache hit) | 重建 | 5-15 min |
| 改 App 源码 | 跳过 (cache hit) | 重建 | 5-15 min |
| 改 apt packages | 重建 | 重建 | 无 |
| 无改动 | 跳过 | 跳过 | 全部 |

### 2. cache.py 子组件哈希支持

扩展 `BuildCache` 支持分阶段哈希：

- `compute_phase_hash(component, phase)` — 计算指定阶段的哈希
- `is_phase_up_to_date(component, phase)` — 检查指定阶段缓存是否有效
- `store_phase(component, phase)` — 保存指定阶段的哈希
- 哈希文件路径：`target/.../rootfs/.base_hash` 和 `target/.../rootfs/.build_hash`

原有的 `compute_hash()`、`is_up_to_date()`、`store()` 接口不变，rootfs 的 `compute_hash` 等价于 Phase 2 哈希（因为 Phase 2 哈希已包含 base hash 作为输入）。

### 3. 修复 App 源码哈希

`_hash_app_sources()` 改为递归 hash 整个 App 目录：

- 遍历 `app/<name>/` 目录下所有文件（排除 `__pycache__`、`.git`、`build/` 等临时目录）
- 按路径排序后依次 hash 文件内容
- 保留 app.yaml 哈希（用于检测元数据变化）
- 新增所有源文件哈希（用于检测代码变化）

对于 external_apps（仓库外 App），使用 git commit hash 作为源码哈希（与 kernel/bootloader 一致）。

### 4. Overlay 目录哈希

新增 `_hash_directory(h, directory)` 工具方法：

- 递归遍历目录下所有文件
- 按相对路径排序
- 依次 hash 文件路径 + 文件内容
- 用于 overlay 目录和 app 源码目录的哈希计算

### 5. Base Rootfs 跨配置共享

当两个 product/variant 的 `rootfs.url` + `rootfs.packages` + `arch` 完全一致时，它们的 base.tar.gz 理论上可以共享。设计上预留此能力：

- base.tar.gz 的存储路径使用哈希命名：`target/<board>/.cache/rootfs-base-<hash>.tar.gz`
- 各 product/variant 的 rootfs 构建过程检查此共享缓存
- 避免同一块板的多个 product 各自构建相同的 base rootfs

## What Doesn't Change

- 构建引擎依赖图不变（DEPENDENCY_GRAPH 结构不动）
- 非 rootfs 组件的缓存逻辑不变（kernel、bootloader 仍用 git commit + patches）
- `RockchipRootfsBuilder` 的构建流程三阶段不变（只是在中间加了缓存检查点）
- 串行构建顺序不变（不做并行构建）

## Risks

- base.tar.gz 快照文件较大（500MB-1GB），磁盘空间需关注
- overlay hash 递归遍历可能在大目录时性能慢（但 overlay 通常很小）
- 跨 product/variant 共享 base.tar.gz 需要确保 hash 输入完全覆盖所有影响因素
