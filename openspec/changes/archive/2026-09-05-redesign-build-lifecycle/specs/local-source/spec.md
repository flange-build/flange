## MODIFIED Requirements

### Requirement: local_path 在顶层 source descriptor 声明

本地组件源码 SHALL 通过 `sources.<name>.local_path` 声明，组件按 `source.name` 引用。descriptor MUST 且只能声明 url 或 local_path 之一；本地来源 MUST NOT 混用远端 revision 字段。构建时 SourceManager SHALL 将用户当前内容复制到目标独立工作目录；共享下载和目标产物不得写入用户原树。

#### Scenario: 组件使用本地源码
- **WHEN** sources.linux 声明 local_path 且 kernel 引用该 source
- **THEN** SourceManager 按内容摘要准备目标副本，不在用户原目录执行 Git 重置或编译

#### Scenario: 来源互斥
- **WHEN** 同一 descriptor 同时声明 url 与 local_path
- **THEN** 配置校验在构建前拒绝该输入

### Requirement: 本地模式跳过源码重置与补丁

本地模式 SHALL 把用户当前内容视为已经准备好的源码快照；目标副本构建 MUST 跳过自动 Git 重置与补丁应用。用户原目录中的未提交内容 MUST 保持不变。原内容不变时目标副本 MAY 保留底层增量产物；原内容变化时 SHALL 重新准备副本，避免把上次目标修改当作用户输入。

#### Scenario: 本地模式不重置原树
- **WHEN** 本地源码含未提交修改，构建器在目标副本生成文件
- **THEN** 用户原树保持原样，目标变更不会回写

#### Scenario: 远端模式修改目标工作树
- **WHEN** 组件使用远端 descriptor
- **THEN** 补丁和编译操作作用于该目标的独立工作树，共享获取仓库不会成为编译目录

### Requirement: 本地 App 目录同样适用

本地 App SHALL 在显式资源工作目录中构建，并以其来源、源码内容、配方、环境和依赖产物构造计划。项目外 local_path 或 app_dirs 来源 MUST 与仓库内 App 使用相同的内容缓存规则；不同来源的同名 App MUST 拥有不同资源身份，不得共享发布目录。不能要求不同绝对来源自动拥有相同资源身份。

#### Scenario: 本地 App 无变化
- **WHEN** 所有计划输入与发布产物保持不变
- **THEN** App 节点允许命中缓存，位置在工具仓库外不构成强制重建理由

#### Scenario: 同名不同来源
- **WHEN** 两个 App 描述符声明相同名称但来源路径不同
- **THEN** 单独构建时使用不同资源输出目录；同一依赖闭包中的名称歧义应被拒绝

## REMOVED Requirements

### Requirement: 本地模式下框架放弃缓存决策
**Reason**: 输入树摘要已覆盖内容、权限、节点类型和链接；位置不再构成禁用缓存的理由。
**Migration**: 使用 TaskPlan 和 ArtifactManifest 查询命中，显式需要重建时使用 force。

## ADDED Requirements

### Requirement: 本地模式使用内容与产物缓存

本地源码 SHALL 纳入具名树输入。相同输入与完整产物允许命中；有效源码内容或元数据变化必须失效，下游依据实际发布的产物身份决定是否重建。

#### Scenario: 修改本地源文件
- **WHEN** 本地 kernel 源码内容或权限改变
- **THEN** kernel 计划指纹改变，缓存解释列出源输入变化；构建前后输入不一致时拒绝发布成功记录
