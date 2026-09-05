# build-plan-artifacts Specification

## Purpose

定义构建计划、具名输入和准确产物之间的统一契约，使执行、缓存解释、增量判定及部署能够消费相同事实，并在并发、损坏、失败和取消时保持可验证的一致性。

## Requirements
### Requirement: 构建计划声明完整契约
每个构建任务 MUST 声明具名输入、依赖、配方和产物，执行、缓存和 why MUST 使用同一计划。
依赖闭包 MUST 拒绝缺失与循环依赖。

#### Scenario: 请求依赖其他库的 App
- **WHEN** 从干净工作区请求构建最终 App
- **THEN** 全部依赖先构建，准确产物用于组成该 App 的编译环境

### Requirement: 输入与产物具有完整身份
树摘要 MUST 包含路径、节点类型、权限、链接目标与文件内容；成功产物 MUST 使用带版本的 manifest 记录。
缓存命中 MUST 同时验证输入和输出完整性。

#### Scenario: 权限变化与产物删除
- **WHEN** 有效输入权限改变或必需 modules 被删除
- **THEN** 缓存拒绝命中并给出明确原因

### Requirement: 可变状态隔离与原子发布
构建工作目录 MUST 按目标和资源隔离；共享可变源 MUST 有锁保护。
快照和成功清单 MUST 通过临时写入、完整验证及原子发布完成。

#### Scenario: 快照保存中断
- **WHEN** 快照写入失败或进程中断
- **THEN** 半成品不能成为可命中的缓存，上次成功记录不被覆盖

### Requirement: 禁用状态决定产物集合
镜像与刷写计划 MUST 使用本次启用的产物集合，不得把残留文件存在当作启用意图。

#### Scenario: 关闭 Recovery 但保留旧文件
- **WHEN** recovery 被禁用且旧镜像仍存在
- **THEN** 本次镜像装配不会使用该旧镜像

### Requirement: 构建存储不得改变目标功能
Linux 内核源码与工作目录 MUST 使用大小写敏感的文件系统；实际构建 MUST 在获取内核源前校验构建存储，并在配置内核时检查实际工作树。检测失败 MUST 给出设置 `flange.toml` 的 `build_dir` 到大小写敏感卷的可操作说明。系统 MUST NOT 根据宿主文件系统隐式关闭 netfilter 或其他目标功能。

#### Scenario: 在大小写不敏感卷启动内核构建
- **WHEN** 当前 build_dir 所在文件系统把不同大小写名称视作同一文件
- **THEN** 在下载和编译前失败，并提示迁移 build_dir，不生成关闭功能的 Kconfig 覆盖
