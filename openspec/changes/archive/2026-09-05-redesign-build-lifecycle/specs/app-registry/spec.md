## RENAMED Requirements

- FROM: `### Requirement: flange list apps 遍历所有来源并标注`
- TO: `### Requirement: flange app list 遍历工作区与工具来源`

## MODIFIED Requirements

### Requirement: 本地 App 目录为默认根

构建系统 SHALL 始终扫描 `<tool_root>/components/app/*/app.yaml` 作为工具内置 App 来源。
工作区显式注册与搜索目录可以覆盖工具来源；缺少 app.yaml 的目录不得作为有效 App 列出。

#### Scenario: 本地 App 被默认识别
- **WHEN** 工具根 components/app/adbd/app.yaml 存在且工作区没有覆盖它
- **THEN** flange app list 包含 adbd 的名称、来源和路径

#### Scenario: 空的本地 App 目录被忽略
- **WHEN** components/app/stub 不含 app.yaml
- **THEN** flange app list 不列出该目录

### Requirement: external_apps 字典支持 local_path 与 git 两种互斥分支

系统 external_apps MUST 为名称到闭合来源声明的映射。每项 MUST 恰好声明 local_path 或 git；
远端可选 branch、commit、tag、recurse_submodules，commit 与 tag 互斥；本地不得声明远端修订字段。
所有类型必须严格，未知 ref 等键 MUST 拒绝。SourceManager 以 descriptor 身份隔离共享下载，并提供目标独立工作树。

#### Scenario: local_path 声明合法
- **WHEN** external_apps.foo.local_path 指向有效 App
- **THEN** 解析本地来源且不触发 Git 操作

#### Scenario: git 声明合法
- **WHEN** external_apps.bar 声明 git 与 tag
- **THEN** 构建准备指定来源的目标工作树，并继续同一 AppSpec/AppBuilder 流程

#### Scenario: 互斥来源或错误类型
- **WHEN** 同时声明 git/local_path、两者都缺失、声明 ref 或 recurse_submodules 使用字符串
- **THEN** 配置加载指出具体字段并在源码准备前失败

### Requirement: external_app_dirs 提供搜索路径，按顺序解析

系统 external_app_dirs SHALL 是可选的路径字符串列表；工具来源注册表按顺序查找 `<dir>/<name>/app.yaml`。
首个命中采用，空列表与未声明等价。此规则不替代工作区 app_dirs 的同名歧义拒绝语义。

#### Scenario: 单个搜索路径命中
- **WHEN** external_app_dirs 中存在所请求 App
- **THEN** 工具来源解析器返回它的规范绝对目录

#### Scenario: 多目录顺序解析
- **WHEN** 系统 external_app_dirs 的两个目录均有同名 App
- **THEN** 采用声明在前的目录

#### Scenario: 空列表等价于未声明
- **WHEN** external_app_dirs 为空列表
- **THEN** 不执行该来源搜索

### Requirement: App 查找优先级固定且显式注册压隐式搜索

AppResolver SHALL 先处理显式路径；名称请求依次使用工作区 `[apps]`、相对解析基准下真实目录、工作区 app_dirs、工具来源注册表。
工具来源注册表内部依次使用 components/app、external_apps、external_app_dirs。
已命中但缺少 app.yaml 的来源 MUST 报错，不回退；多个工作区 app_dirs 同名命中 MUST 要求显式注册消歧。
同一闭包含同名不同源的 App MUST 被拒绝。

#### Scenario: 工作区显式来源覆盖工具
- **WHEN** [apps] 注册 foo，工具内置来源也有 foo
- **THEN** 名称请求使用工作区注册路径

#### Scenario: external_apps 命中后不回退
- **WHEN** 工具显式注册路径损坏而后续搜索目录含有同名 App
- **THEN** 解析失败，不使用后续目录掩盖损坏声明

#### Scenario: 工作区搜索歧义
- **WHEN** 两个 app_dirs 都含 foo，且 [apps] 未显式注册 foo
- **THEN** 解析失败并列出冲突来源

### Requirement: local_path 与 external_app_dirs 的路径解析规则一致

系统 external_apps.local_path 与 external_app_dirs SHALL 支持用户目录展开，并相对 tool_root 归一化。
工作区 [apps] 与 app_dirs SHALL 相对 flange.toml 所在目录归一化。最终实际路径 MUST 通过统一挂载传入容器，不在容器重解释宿主用户目录。

#### Scenario: 用户目录展开
- **WHEN** 本地来源声明用户目录路径
- **THEN** 宿主配置边界存储已解析的绝对路径

#### Scenario: 工作区与工具路径分离
- **WHEN** 两处均声明相对路径且位于不同根目录
- **THEN** 各自仅使用对应声明根解析一次

### Requirement: flange app list 遍历工作区与工具来源

flange app list SHALL 合并工具来源、工作区 app_dirs 与 [apps]，返回名称、路径与来源。
工作区显式条目优先于工作区搜索目录，工作区来源优先于工具来源；不再要求旧的固定文本布局或 also-found 行。
JSON 与人类输出 SHALL 从同一结果渲染；未获取的远端来源不得因列表操作自动下载。

#### Scenario: 工作区覆盖工具条目
- **WHEN** 工具与 [apps] 同时注册 foo
- **THEN** 列表主条目为工作区 foo，并包含其实际路径

#### Scenario: 搜索目录同名歧义
- **WHEN** app_dirs 中存在同名不同路径且无显式覆盖
- **THEN** 列表报出歧义并要求 [apps] 消歧

### Requirement: flange app create SHALL 默认创建到调用者目录

flange app create SHALL 默认使用调用者目录为父目录，--dir SHALL 指定父目录并支持相对路径与用户目录展开。
create MUST 不覆盖既有工程，失败清理本次未完成输出，不自动修改工作区或系统注册表。
旧 flange create app 入口被移除；用户可以使用生成路径立即 plan/build，也可以自行声明工作区 [apps]/app_dirs。
支持架构 SHALL 与 AppSpec 一致，已选目标时缺省使用其用户空间架构，否则为 aarch64。

#### Scenario: 在仓库外创建 App
- **WHEN** 在 /work/vendor 执行 flange app create demo
- **THEN** 创建 /work/vendor/demo 且不修改工具仓库配置

#### Scenario: 指定父目录
- **WHEN** 执行 flange app create demo --dir ../apps
- **THEN** 在调用目录解析出的 ../apps/demo 创建工程

#### Scenario: 目标已存在
- **WHEN** 最终目标目录已经存在
- **THEN** 创建失败且原内容保持不变

### Requirement: ad-hoc App 路径 SHALL 优先于 registry 名称解析

显式路径 SHALL 直接校验其 app.yaml，相对路径基于调用位置；build.deps 内相对路径基于声明 App。
名称请求按统一 AppResolver 优先级解析。宿主与容器 MUST 访问同一规范源码路径，最终编译在隔离副本执行。

#### Scenario: 从仓库外当前目录构建 App
- **WHEN** 当前工作区下的 App 目录含 app.yaml 且执行 flange app build
- **THEN** 解析当前 App 并求完整依赖闭包，编译不污染原始源码目录

## REMOVED Requirements

### Requirement: flange create app 默认写入 components/app/\<name\>/
**Reason**: 旧动词优先入口已移除，默认创建位置统一为调用者目录。
**Migration**: 使用 flange app create；工具内容开发者可以显式传 --dir components/app。

### Requirement: flange create app 支持 --dir 指定父目录
**Reason**: 旧入口移除，父目录语义由资源优先命令承接。
**Migration**: 使用 flange app create <name> --dir <父目录>。

### Requirement: create app 生成 out-of-tree 位置后输出注册指引
**Reason**: 路径请求无需修改系统注册表；固定旧注册提示不再是公开输出契约。
**Migration**: 使用路径 plan/build，按需要维护 flange.toml 中的 [apps]/app_dirs。
