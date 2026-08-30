# shared-repo-references Specification

## Purpose

定义所有源码组件共享的唯一 source descriptor 与引用语义：仓库地址、版本锚点（commit / tag / branch / local_path）与子路径只在一处声明，组件按名引用；多个组件引用同一名字即共享同一份检出。

## Requirements

### Requirement: 顶层命名 source

配置 MUST 在顶层 `sources.<name>` 声明 source descriptor。descriptor MUST 且
只能包含非空 `url` 或 `local_path` 之一；远端 MAY 声明 `branch`、`commit`、
`recurse_submodules`，本地 source MUST NOT 声明这些 revision 字段。

#### Scenario: 远端 source

- **WHEN** `sources.linux` 声明 `url`、`branch` 与 `commit`
- **THEN** SourceManager 获取该仓库并固定到声明的 commit

#### Scenario: 本地 source

- **WHEN** `sources.linux` 只声明 `local_path`
- **THEN** SourceManager 直接使用该目录且不执行 git 操作

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
- **THEN** 三者共享一次 checkout，并分别返回各自子目录

#### Scenario: 未声明的引用

- **WHEN** `kernel.source.name` 不存在于顶层 `sources`
- **THEN** canonical validator 报错并指出未知 source name

#### Scenario: subpath 越界

- **WHEN** `source.subpath` 为绝对路径或包含 `..`
- **THEN** canonical validator 拒绝配置

### Requirement: checkout 身份隔离

远端 checkout 目录 MUST 由完整 descriptor 的稳定摘要决定，使相同 URL 的不同
branch/commit 互不覆盖；多个组件引用完全相同 descriptor 时 MUST 复用目录。

#### Scenario: revision 身份不同

- **WHEN** 两个 source 使用相同 URL 但 commit 不同
- **THEN** SourceManager 将其放入不同 checkout 目录
