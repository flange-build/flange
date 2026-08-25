## MODIFIED Requirements

### Requirement: 命名仓库声明

配置中必须（SHALL）在顶层 `sources` 对象声明所有源码。每个 `sources.<name>` descriptor MUST 包含远端 `url`，可包含 `branch`、`commit`、`recurse_submodules`，或者声明与远端字段互斥的 `local_path`。独立组件源码与共享仓库 MUST 使用相同 descriptor，不得再区分组件内 `repo` 和顶层 `repos`。

#### Scenario: 单一组件源码存在
- **WHEN** 配置声明 `sources.kernel` 并由 Kernel 组件引用
- **THEN** SourceManager 按该 descriptor 获取源码

#### Scenario: 多个 source 并存
- **WHEN** 配置声明 `sources.linux-a733` 和 `sources.u-boot-aw2501`
- **THEN** 两者按各自 descriptor 与内容身份独立获取，互不污染

#### Scenario: 本地路径与远端字段互斥
- **WHEN** 一个 source descriptor 同时声明 `local_path` 和 `url`
- **THEN** validator 在 SourceManager 执行前失败

### Requirement: 组件通过 from_repo 引用命名仓库

组件必须（SHALL）通过 `source.name` 引用顶层 `sources`，并 MAY 通过 `source.subpath` 指定源码根内子路径。所有组件 MUST 使用该引用结构，不得接受 `from_repo` alias。

#### Scenario: 组件引用 source 根
- **WHEN** Bootloader 配置为 `source: {name: "u-boot-aw2501"}`
- **THEN** SourceManager 返回该 source checkout 根目录

#### Scenario: 组件引用 source 子路径
- **WHEN** Kernel 配置为 `source: {name: "linux-a733", subpath: "src"}`
- **THEN** SourceManager 返回该 checkout 的 `src` 子目录

#### Scenario: 多组件引用同一 source
- **WHEN** kernel、kernel_bsp、kernel_device 引用同一个 source name
- **THEN** SourceManager 只获取一次源码，并按各自 subpath 返回路径

#### Scenario: 引用不存在的 source
- **WHEN** 组件引用 `unknown-source` 但顶层 `sources` 未声明
- **THEN** validator 失败并包含缺失的 source name

### Requirement: 路径解析优先级

SourceManager SHALL 先解析组件的 `source.name`，再读取唯一 source descriptor；descriptor 为 `local_path` 时直接使用已校验的本地目录，descriptor 为远端时按 URL/revision 获取 checkout，最后追加组件 `source.subpath`。组件内不得再声明会形成优先级的 `local_path`、`from_repo` 或 `repo` 字段。

#### Scenario: local source
- **WHEN** 被引用 descriptor 只声明合法 `local_path`
- **THEN** SourceManager 返回该路径与组件 subpath
- **AND** 不执行 clone

#### Scenario: remote source
- **WHEN** 被引用 descriptor 声明 URL 和 commit
- **THEN** SourceManager 获取并 checkout 确切 commit 后返回组件 subpath

### Requirement: 命名仓库存储位置隔离

远端 source checkout MUST 按 descriptor 内容身份隔离；缓存身份至少包含规范化 URL、branch、commit 与 submodule 策略。同名 source descriptor 的内容变化 MUST NOT 复用不匹配的可变工作树，不同组件引用完全相同 descriptor 时 SHOULD 复用一次 checkout。

#### Scenario: 同名 source 切换 commit
- **WHEN** `sources.kernel.commit` 从 commit A 改为 commit B
- **THEN** SourceManager 不把仍位于 commit A 的工作树作为有效结果返回

#### Scenario: 共享 descriptor 复用
- **WHEN** 两个组件引用同一 source name 和 descriptor
- **THEN** 两者复用一次获取结果并分别解析 subpath
