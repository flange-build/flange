## MODIFIED Requirements

### Requirement: 组件缓存 SHALL 使用 Merkle 内容哈希与必需产物双重门禁

`BuildCache` SHALL 将上游组件哈希、影响该组件的 FINAL_CONFIG、构建逻辑、源码 git HEAD、仓库内源码/共享库、补丁和组件特化输入混合为稳定内容哈希。`is_up_to_date(component)` SHALL 同时要求 `.build_hash` 与当前哈希一致且该组件的动态必需产物完整存在；任一条件不满足都必须重建。缓存记录 MUST 在构建完成且产物门禁通过后按构建后的输入身份原子写入。

#### Scenario: 上游内容变化级联失效

- **WHEN** kernel 源码、配置、构建逻辑或补丁变化，rootfs/boot/image 消费该上游组件
- **THEN** kernel 哈希变化并通过 Merkle 依赖使相关下游缓存失效

#### Scenario: 哈希存在但产物被删除

- **WHEN** `.build_hash` 与当前输入一致，但 kernel 的 Image/DTB、App 声明的 deb、overlay 的 dtbo 或 rootfs 镜像缺失
- **THEN** `is_up_to_date()` 返回 false

#### Scenario: 构建期间源码身份变化

- **WHEN** 缓存判定后、缓存保存前 git HEAD 被源码准备流程更新
- **THEN** `.build_hash` 记录更新后的 HEAD 对应哈希

### Requirement: Rootfs SHALL 支持可共享的 Phase 1 base cache

Rootfs 构建 SHALL 将已校验 SHA256 的 ubuntu-base 解压和 apt package 安装作为 Phase 1，其哈希至少覆盖 rootfs URL、SHA256、排序后的 packages、extra APT sources、arch 与 emulator。下载 MUST 使用临时文件并在摘要校验成功后原子替换。base snapshot SHALL 存放在板级共享 cache 中，使相同输入的 product/variant 可复用；overlay、App、账号和镜像路由变化只使完整 rootfs hash 失效，不得无故使 base hash 失效。

#### Scenario: 仅修改 overlay

- **WHEN** board/rootfs overlay 内容变化而 URL、SHA256、packages、extra APT sources、arch 与 emulator 不变
- **THEN** rootfs 完整缓存失效但 Phase 1 base cache 继续命中

#### Scenario: 修改 apt packages 或软件源

- **WHEN** rootfs packages 集合或 extra APT sources 变化
- **THEN** Phase 1 base hash 和 rootfs 完整 hash 都变化

#### Scenario: 跨 variant 共享 base snapshot

- **WHEN** 同一 board 的两个 variant 具有相同 Phase 1 输入
- **THEN** 两者计算相同 base hash 并使用同一板级 base snapshot 路径

#### Scenario: 下载摘要不匹配

- **WHEN** 已有或新下载的 rootfs tarball SHA256 与配置不一致
- **THEN** 系统不得使用该文件，新下载失败时清理临时文件并报告错误

### Requirement: App cache MUST 递归覆盖仓库内源码

App 组件 hash MUST 覆盖 `rootfs.custom_packages` 与启用的 recovery custom packages，并递归 hash `components/app/<name>/` 及项目 `components/` 内注册来源的非临时文件；新增文件、改名、共享库 `.so` 或内容变化都必须使 App hash 变化。构建目录、VCS 元数据、`__pycache__` 与编译中间产物 SHALL 被排除。项目外 `local_path` 和 `external_app_dirs` MUST 继续强制组件及下游进入底层增量构建。

#### Scenario: 修改非 app.yaml 源文件

- **WHEN** custom package 的脚本、配置、源码或 `.so` 载荷内容变化
- **THEN** App hash 变化并级联使消费其 deb 的 rootfs 缓存失效

#### Scenario: 仓库内注册的 vendor App 无变化

- **WHEN** App 通过 `external_apps.local_path` 指向项目 `components/` 内目录且内容未变化
- **THEN** App 及其下游允许命中缓存

#### Scenario: 项目外本地 App

- **WHEN** App 来源位于项目 `components/` 之外的 `local_path` 或 `external_app_dirs`
- **THEN** App 及其下游放弃缓存命中并进入底层增量构建

#### Scenario: 仅生成临时文件

- **WHEN** App 目录新增 `__pycache__/*.pyc`、`.o` 或 build 目录派生物
- **THEN** App hash 保持不变

### Requirement: 分阶段缓存接口 SHALL 可独立读写

`compute_phase_hash`、`store_phase` 和 `is_phase_up_to_date` SHALL 为 rootfs/recovery base 阶段提供独立于完整组件 `.build_hash` 的 hash 文件，base 与完整构建缓存不得互相覆盖；阶段哈希记录 MUST 使用原子替换写入。

#### Scenario: 同时保存 base 与完整 rootfs hash

- **WHEN** 构建器先保存 `.base_hash` 再保存 `.build_hash`
- **THEN** 两个缓存状态可独立查询，任一输入变化按各自覆盖范围失效

## ADDED Requirements

### Requirement: branch 源码身份 MUST 在缓存判定前解析

构建引擎 MUST 在查询组件缓存前同步该组件实际使用的 branch 仓库及相关 OOT/firmware/App git 仓库。未固定 commit/tag 的 branch 在远端 HEAD 与本地已缓存 HEAD 相同时 MUST 允许命中，不得仅因声明 branch 而强制重建。

#### Scenario: branch HEAD 未变化

- **WHEN** 连续两次构建跟踪同一 branch，第二次同步后 HEAD 未变化且产物完整
- **THEN** 组件缓存命中并跳过实际构建

#### Scenario: branch HEAD 前进

- **WHEN** 第二次构建前远端 branch HEAD 发生变化
- **THEN** 同步后的源码 HEAD 改变组件哈希并使组件及下游缓存失效
