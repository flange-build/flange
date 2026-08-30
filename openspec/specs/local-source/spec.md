# local-source Specification

## Purpose

定义 `local_path` 源码模式的语义：开发者把某个组件指向自己本机正在改的源码树
时，框架在**源码处理**与**缓存决策**两侧分别该做什么。

## Requirements

### Requirement: local_path 在顶层 source descriptor 声明

本地源码 SHALL 通过顶层 `sources.<name>.local_path` 声明，组件按
`source.name` 引用（见 `shared-repo-references`）。descriptor MUST 且只能
声明 `url` 或 `local_path` 之一；声明 `local_path` 时 MUST NOT 声明
`branch` / `commit` 之类的 revision 字段。

#### Scenario: 组件使用本地源码
- **WHEN** `sources.linux` 只声明 `local_path`，且 `kernel.source.name == "linux"`
- **THEN** SourceManager 直接使用该目录，不执行任何 git 操作

#### Scenario: 来源互斥
- **WHEN** 同一 descriptor 同时声明 `url` 与 `local_path`
- **THEN** canonical validator 在构建前拒绝配置

### Requirement: 本地模式跳过源码重置与补丁

组件构建在本地模式下 MUST 跳过 `git reset` 与全部补丁应用，直接用源码树的
当前状态构建。

理由是这个目录属于开发者：重置会丢掉未提交的改动，重复打补丁会失败或产生
重复 hunk。这一判据 MUST 与缓存侧共用 `builder/source.py` 的同一个函数 ——
两处各写一份的后果是 `local_path` 的两半语义只兑现一半（缓存放弃了决策，
构建却仍在重置用户的工作树）。

#### Scenario: 本地模式不重置源码
- **WHEN** 组件的 source 声明了 `local_path`
- **THEN** 构建不执行 `git reset`，也不应用任何补丁，并在状态行说明原因

#### Scenario: 远端模式保持既有行为
- **WHEN** 组件的 source 声明的是 `url`
- **THEN** 构建照常重置源码树并按顺序应用补丁

### Requirement: 本地模式下框架放弃缓存决策

当组件自身**或任意传递上游**声明了 `local_path` 时，`is_up_to_date` MUST
返回 False，强制重建并级联到下游。

不做源码树哈希是有意的：这个目录的内容变化不走 git，没有可靠的廉价指纹；
按树哈希会产生假命中（"内容变了但哈希没变"），而假命中在这里意味着开发者
改了代码却拿到旧产物。真正的增量交给底层构建系统（make / mke2fs）自己做,
它们本来就有可靠的时间戳依赖。

#### Scenario: 本地组件每次都重建
- **WHEN** kernel 的 source 声明了 `local_path`
- **THEN** 每次 `flange build kernel` 都进入构建，由 make 决定编译哪些文件

#### Scenario: 级联到下游
- **WHEN** kernel 声明了 `local_path`
- **THEN** boot 与 image 也强制重建，确保下游产物基于最新的 kernel 产物组装

#### Scenario: 缓存决策可解释
- **WHEN** 对本地模式的组件执行 `flange why`
- **THEN** 输出说明"组件或其上游声明了 local_path，框架放弃缓存决策"

### Requirement: 本地 App 目录同样适用

`external_apps` / `external_app_dirs` 指向的本地 App 目录 MUST 与组件的
`local_path` 适用同一规则：app 组件强制重建并级联。App 描述符进入哈希输入
时，绝对 `local_path` MUST 归一化为项目相对路径，使同一份源码在不同机器上
算出相同的哈希。

#### Scenario: 本地 App 触发 app 组件重建
- **WHEN** 某个 custom package 指向本地 App 目录
- **THEN** app 组件强制重建

#### Scenario: 绝对路径不进哈希
- **WHEN** 两台机器把同一个仓库检出到不同目录
- **THEN** 两边算出的 app 哈希相同
