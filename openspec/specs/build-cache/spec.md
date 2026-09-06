# build-cache Specification

## Purpose

定义构建组件的稳定内容哈希、Merkle 依赖级联失效和动态必需产物门禁，以及 rootfs
Phase 1/Phase 2 分阶段缓存、跨 product/variant 复用与失效边界契约。
## Requirements
### Requirement: 组件缓存 SHALL 使用 Merkle 内容哈希与必需产物双重门禁

`BuildCache(context=WorkspaceContext)` SHALL 直接消费 `TaskPlan`。`is_up_to_date(plan, manifests)` SHALL 同时验证具名输入指纹、依赖产物身份、版本化成功 manifest 和全部文件/目录产物的内容与元数据。旧 `.build_hash` MUST NOT 被接受为成功记录。

依赖边 SHALL 引用上游 `ArtifactManifest.identity`，不再以其输入摘要代替实际结果。配方执行前后 SHALL 计算同一份计划的指纹；输入变化、缺少必需产物、失败或取消 MUST 阻止发布成功 manifest。成功记录 SHALL 原子写入 `<target_dir>/<component>/manifest.json`。

#### Scenario: 上游重建产生相同内容

- **WHEN** kernel 的输入变化导致重建，但发布的完整产物身份与上次相同
- **THEN** kernel 成功记录更新，而只消费这些产物的下游允许继续命中

#### Scenario: 上游产物内容变化

- **WHEN** kernel 发布的 Image、DTB 或 modules 内容改变
- **THEN** 消费 kernel 的任务输入指纹改变，并根据其实际重建结果继续传播

#### Scenario: 输入相同但产物被删除或修改

- **WHEN** 输入摘要不变，但必需产物被删除、权限改变、链接目标改变或文件内容改变
- **THEN** 缓存查询返回 miss 并给出受影响产物名称

#### Scenario: 执行期间源码身份变化

- **WHEN** 构建开始后、本次成功记录发布前，本地源内容或 Git HEAD 改变
- **THEN** 本次缓存发布失败，不得把变化后的输入标记为已经执行

### Requirement: Rootfs SHALL 支持可共享的 Phase 1 base cache

`builder.rootfs_base.base_plan(config, component, context)` SHALL 为 rootfs/recovery 构造同一配方的具名输入，覆盖 ubuntu-base URL/SHA256/文件名、所选组件排序后的 packages、install_recommends、extra_apt_sources、用户态 ABI、emulator、配方实现和实际构建环境身份。`build_base(plan, ...)` MUST 从该计划读取执行参数，不重新推导另一套缓存字段。

快照 SHALL 存放于 `<build_root>/cache/rootfs-base/base-<input_digest>.tar.zst`，由同一 build_root 下具备相同 Phase 1 输入的 board/product/variant 及 rootfs/recovery 共享。overlay、App、账号和镜像布局不是 Phase 1 输入。

#### Scenario: 相同 base 输入跨目标与组件共享

- **WHEN** rootfs 与 recovery 或两个不同目标的 Phase 1 输入完全相同
- **THEN** 两者得到相同快照路径，成功快照允许复用

#### Scenario: Recovery 专有 APT 行为变化

- **WHEN** 仅修改 recovery.install_recommends、packages 或 extra_apt_sources
- **THEN** Recovery 的 Phase 1 指纹与执行行为同步变化；rootfs 的 Phase 1 指纹保持不变

#### Scenario: 仅修改 overlay

- **WHEN** 板级 overlay 变化而 Phase 1 输入不变
- **THEN** 完整 Rootfs 计划失效，成功 base 快照继续可用

#### Scenario: 下载摘要不匹配

- **WHEN** 已有或新下载的 tarball 与声明 SHA256 不同
- **THEN** 该文件不得被使用，新下载半成品被清理，只有校验成功的文件可以原子发布

### Requirement: App cache MUST 递归覆盖仓库内源码

每个 App 节点 SHALL 以资源身份、声明配置、源码树、构建配方、工具链/环境和依赖产物身份形成计划。源码摘要 MUST 包含普通文件内容、权限、节点类型和符号链接目标；仅排除明确的 VCS 元数据与工作区派生产物路径，不能全局排除所有同名 `build` 目录。

项目内外的本地 App SHALL 使用相同的内容缓存规则，不得仅因位于项目外就强制放弃缓存。系统构建 SHALL 每次执行 App 闭包调度，由节点缓存决定复用，并生成准确的 `AppBuildReport` 供 Rootfs/Recovery 消费。

#### Scenario: 项目外本地 App 未变化

- **WHEN** out-of-tree App 的全部计划输入和 manifest 产物均未变化
- **THEN** 该 App 节点允许缓存命中

#### Scenario: 单个 App 源码变化

- **WHEN** 某 App 的源码、脚本或共享库载荷发生变化
- **THEN** 该节点失效；独立 App 不受影响，其依赖者根据实际发布产物身份决定失效

#### Scenario: 源码目录恰好命名为 build

- **WHEN** 有效 App 源目录或其中一个源码子目录名为 build
- **THEN** 该目录内容仍进入输入身份，除非路径被明确声明为本次派生目录

### Requirement: 分阶段缓存接口 SHALL 可独立读写

Phase 1 SHALL 使用 `TaskPlan.fingerprint()` 与 `SnapshotStore`，完整组件 SHALL 使用 `BuildCache` 与 `ArtifactManifest`；两者不共享成功文件，不提供 `.base_hash`/`.build_hash` 双标记协议。每份快照 MUST 有单独版本化 manifest，记录输入身份与归档完整内容身份。

`SnapshotStore.save` SHALL 在锁内写唯一临时归档，完整读取 tar 验证并原子替换，再发布 manifest。`restore` MUST 校验 manifest 与归档；损坏归档或解压失败不能命中，部分解压内容必须清理，之后重新构建。

#### Scenario: 保存快照中断

- **WHEN** tar 写入过程中失败或取消
- **THEN** 临时文件不能成为成功快照，之前完整快照与成功记录保持可用

#### Scenario: 已有归档缺少有效 manifest

- **WHEN** 缓存目录仅存在旧归档或损坏的 manifest
- **THEN** 视为 cache miss，重新构建并发布新格式完整记录

### Requirement: branch 源码身份 MUST 在缓存判定前解析

实际构建 MUST 在查询组件缓存前同步所消费的 branch 源及 OOT/固件/App 仓库，然后以解析的 Git HEAD 形成计划。只读 plan/why MUST NOT fetch、创建下载目录或启动构建；未准备的源应返回明确的 unresolved 输入或阻塞原因。

#### Scenario: branch HEAD 未变化

- **WHEN** 第二次构建同步后 HEAD 未变化，其他输入相同且产物完整
- **THEN** 组件缓存允许命中

#### Scenario: branch HEAD 前进

- **WHEN** 第二次构建准备源时远端 HEAD 前进
- **THEN** 当前组件计划失效，下游是否失效由本次实际产物身份决定

#### Scenario: 从干净工作区查询计划

- **WHEN** 尚未下载源码时请求 plan 或 why
- **THEN** 返回结构化待准备信息，不创建构建目录、锁、日志或下载内容

### Requirement: APT 互斥 SHALL 跟随真实共享目录

App、rootfs/recovery 及内置模板下载的 APT 访问 SHALL 按实际缓存源目录协调互斥，
MUST NOT 仅使用工作区 ID 决定共享缓存锁。APT 命令参数、bind mount 源与锁身份 SHALL 一致。
共享索引的读取 SHALL 与更新互斥，独立目录 MUST NOT 因无关工作区而被全局串行化。

#### Scenario: 两个外部工作区共用工具缓存
- **WHEN** 两个工作区同时准备 App 的 APT 依赖
- **THEN** 同一共享缓存的 update/install 事务串行完成，不因工作区锁互不相见而抢占 APT 锁

#### Scenario: App 与 rootfs 共用下载缓存
- **WHEN** App 安装依赖，rootfs/recovery 正在使用同一真实下载目录
- **THEN** 双方通过同一资源锁串行访问，即使其容器内路径不同

### Requirement: APT 锁 SHALL 保持稳定身份和固定顺序

所有 APT 目录 SHALL 先规范化、去重并按固定顺序加锁；锁文件 MUST 位于 APT 清理范围外，
MUST NOT 删除或替换 APT 自己的锁。异常、取消及部分加锁失败 SHALL 释放已取得的资源锁。
目标和资源构建锁 SHALL 位于 APT 锁外层，APT 锁 MUST NOT 跨越无关编译操作。

#### Scenario: 清理与失败恢复
- **WHEN** APT clean 清空下载缓存，或 APT 命令失败退出
- **THEN** Flange 锁节点保持不变，后续请求可在前一事务释放后正常进入

#### Scenario: 多资源获取顺序不同
- **WHEN** 两个请求以不同参数顺序描述相同目录集合
- **THEN** 实际加锁顺序相同，避免逆序等待
