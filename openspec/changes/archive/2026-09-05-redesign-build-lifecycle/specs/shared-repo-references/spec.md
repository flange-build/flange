## MODIFIED Requirements

### Requirement: 顶层命名 source

配置 MUST 在顶层 `sources.<name>` 声明 source descriptor。descriptor MUST 且
只能包含非空 `url` 或 `local_path` 之一；远端 MAY 声明 `branch`、`commit`、
`recurse_submodules`，本地 source MUST NOT 声明这些 revision 字段。

#### Scenario: 远端 source

- **WHEN** `sources.linux` 声明 `url`、`branch` 与 `commit`
- **THEN** SourceManager 获取该仓库并固定到声明的 commit

#### Scenario: 本地 source

- **WHEN** `sources.linux` 只声明 `local_path`
- **THEN** SourceManager 从该目录准备目标独立副本，不在用户原树执行 Git 或编译操作

#### Scenario: 来源互斥

- **WHEN** 同一 descriptor 同时声明 `url` 与 `local_path`
- **THEN** canonical validator 在构建前拒绝配置

### Requirement: 组件使用统一 source 引用

组件 MUST 通过 `source.name` 引用顶层 source，并 MAY 用 `source.subpath`
选择 source 根内的安全相对路径。组件不得直接声明 URL、本地路径或其他来源
alias。

#### Scenario: 组件引用 source 根

- **WHEN** `bootloader.source == {name: "u-boot"}`
- **THEN** SourceManager 返回 `sources.u-boot` 对应 checkout 根目录

#### Scenario: 多组件共享 checkout

- **WHEN** kernel、kernel_bsp 与 kernel_device 引用同一 source name 但使用不同 subpath
- **THEN** 同一目标内三者共享该 descriptor 的独立工作树，并返回各自子目录；不同目标不共享可变工作树

#### Scenario: 未声明的引用

- **WHEN** `kernel.source.name` 不存在于顶层 `sources`
- **THEN** canonical validator 报错并指出未知 source name

#### Scenario: subpath 越界

- **WHEN** `source.subpath` 为绝对路径或包含 `..`
- **THEN** canonical validator 拒绝配置

### Requirement: checkout 身份隔离

共享获取仓库 SHALL 位于 `<build_root>/sources/repos/<descriptor-digest>/`，身份由完整远端 descriptor 决定。目标可变工作树 SHALL 位于 `<build_root>/work/<target.key>/sources/<worktree-id>/`。SourceManager MUST 在仓库锁内同步共享源并准备目标工作树；实际构建与 source fetch MUST 遵循目标锁先于共享仓库锁的顺序。

#### Scenario: revision 身份不同
- **WHEN** 两个 source 使用相同 URL 但不同 commit
- **THEN** 两者使用不同 descriptor 获取仓库，互不覆盖

#### Scenario: 相同源供多个目标使用
- **WHEN** debug 与 release 引用相同 descriptor
- **THEN** 两者复用获取仓库，但配置、补丁和编译写入不同的目标工作树
