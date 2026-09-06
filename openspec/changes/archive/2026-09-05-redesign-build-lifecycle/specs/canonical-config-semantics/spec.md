## MODIFIED Requirements

### Requirement: Canonical schema 拒绝未知和无消费者字段

系统配置所有真实入口 MUST 执行相同的闭合结构、严格类型与跨字段校验，不得根据 dict 子类身份跳过关键规则。
固定字段对象 MUST 拒绝未知键，动态名称仅允许出现在显式声明的映射；列表、布尔值和整数 MUST NOT 通过隐式转换接受错误类型。
未知字段、无生产消费者字段、无效 source 引用及互斥组合 MUST 在构建前失败，错误 MUST 指出字段路径、期望类型和中文纠正建议。

#### Scenario: 普通 dict 与求值结果一致
- **WHEN** 普通 dict 或 ResolvedConfig 包含 `recovery.enabeld` 或字符串 `systemd.auto_start`
- **THEN** 对应系统/App 边界均拒绝未知键或错误类型，不静默采用默认值

#### Scenario: 死参数被拒绝
- **WHEN** App 声明无消费者的 `capabilities`、`lib.headers_dir` 或 `build.outputs`
- **THEN** AppSpec 在执行前拒绝该字段；头文件通过 install staging 或显式 install 映射交付

#### Scenario: source 引用不存在
- **WHEN** `kernel.source.name` 在顶层 `sources` 中不存在
- **THEN** validator 失败并包含缺失的 source name

#### Scenario: 动态名称与结构维度分离
- **WHEN** `sources.product` 是符合 source descriptor 的合法动态条目
- **THEN** 校验器按 source 结构校验它，不因其名称为 product 而误判成未求值条件

## ADDED Requirements

### Requirement: 作者输入与派生配置 MUST 分层校验

Jsonnet 作者输入 MUST 在包集合与 Package 展开前完成结构校验，最终 canonical JSON MUST 在展开后再次完整校验。
`packages_meta` 与 `boot.package_overlay_sources` MUST 仅由展开器生成；配置作者不得注入这些派生字段。
系统字段 MUST 有明确默认值、合法组合、生产消费者及计划输入归属。

#### Scenario: 原始字段类型错误
- **WHEN** Jsonnet 的 rootfs.packages 是字符串而非数组
- **THEN** 求值边界在展开之前指出 rootfs.packages 应为列表

#### Scenario: 配置作者注入包元数据
- **WHEN** 作者 Jsonnet 声明 packages_meta
- **THEN** 配置解析失败并说明该字段是派生结果

### Requirement: Rootfs 与 recovery 的 APT 声明 MUST 使用相同边界

rootfs 和 recovery 的 packages、install_recommends 与 extra_apt_sources MUST 以严格字段进入共用 Phase 1 计划。
APT 源 MUST 使用唯一安全名称及带可信 SHA256 的 key 下载 descriptor；推荐依赖只接受布尔值。

#### Scenario: Recovery 声明额外源与推荐依赖
- **WHEN** recovery 声明合法 extra_apt_sources 与 install_recommends=true
- **THEN** 配置成功解析，基础计划记录同一份 APT 输入并驱动真实安装命令

#### Scenario: Recovery key 摘要错误
- **WHEN** recovery 的额外源 key.sha256 不是 64 位十六进制字符串
- **THEN** 配置在网络访问前失败并指出具体字段
