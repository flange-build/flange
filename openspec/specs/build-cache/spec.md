# build-cache Specification

## Purpose

定义构建组件的稳定内容哈希、Merkle 依赖级联失效和动态必需产物门禁，以及 rootfs
Phase 1/Phase 2 分阶段缓存、跨 product/variant 复用与失效边界契约。

## Requirements
### Requirement: 组件缓存 SHALL 使用 Merkle 内容哈希与必需产物双重门禁

`BuildCache` SHALL 将上游组件哈希、FINAL_CONFIG、源码/补丁和组件特化输入混合为稳定内容哈希。`is_up_to_date(component)` SHALL 同时要求 `.build_hash` 与当前哈希一致且该组件的动态必需产物存在；任一条件不满足都必须重建。

#### Scenario: 上游内容变化级联失效

- **WHEN** kernel 源码、配置或补丁变化，rootfs/boot/image 消费该上游组件
- **THEN** kernel 哈希变化并通过 Merkle 依赖使相关下游缓存失效

#### Scenario: 哈希存在但产物被删除

- **WHEN** `.build_hash` 与当前输入一致，但 kernel 的 Image/DTB 或 rootfs 镜像缺失
- **THEN** `is_up_to_date()` 返回 false

### Requirement: Rootfs SHALL 支持可共享的 Phase 1 base cache

Rootfs 构建 SHALL 将 ubuntu-base 解压和 apt package 安装作为 Phase 1，其哈希至少覆盖 rootfs URL、排序后的 packages、arch 与 emulator。base snapshot SHALL 存放在板级共享 cache 中，使相同输入的 product/variant 可复用；overlay、App、账号和镜像路由变化只使完整 rootfs hash 失效，不得无故使 base hash 失效。

#### Scenario: 仅修改 overlay

- **WHEN** board/rootfs overlay 内容变化而 URL、packages、arch 与 emulator 不变
- **THEN** rootfs 完整缓存失效但 Phase 1 base cache 继续命中

#### Scenario: 修改 apt packages

- **WHEN** rootfs packages 集合变化
- **THEN** Phase 1 base hash 和 rootfs 完整 hash 都变化

#### Scenario: 跨 variant 共享 base snapshot

- **WHEN** 同一 board 的两个 variant 具有相同 Phase 1 输入
- **THEN** 两者计算相同 base hash 并使用同一板级 base snapshot 路径

### Requirement: App cache MUST 递归覆盖仓库内源码

App 组件 hash MUST 覆盖 `rootfs.custom_packages` 与启用的 recovery custom packages，并递归 hash `components/app/<name>/` 中非临时文件；新增文件、改名或内容变化都必须使 App hash 变化。构建目录、VCS 元数据、`__pycache__` 与编译派生物 SHALL 被排除。

#### Scenario: 修改非 app.yaml 源文件

- **WHEN** custom package 的脚本、配置或源码文件内容变化
- **THEN** App hash 变化并级联使消费其 deb 的 rootfs 缓存失效

#### Scenario: 仅生成临时文件

- **WHEN** App 目录新增 `__pycache__/*.pyc` 或 build 目录派生物
- **THEN** App hash 保持不变

### Requirement: 分阶段缓存接口 SHALL 可独立读写

`compute_phase_hash`、`store_phase` 和 `is_phase_up_to_date` SHALL 为 rootfs/recovery base 阶段提供独立于完整组件 `.build_hash` 的 hash 文件，base 与完整构建缓存不得互相覆盖。

#### Scenario: 同时保存 base 与完整 rootfs hash

- **WHEN** 构建器先保存 `.base_hash` 再保存 `.build_hash`
- **THEN** 两个缓存状态可独立查询，任一输入变化按各自覆盖范围失效
