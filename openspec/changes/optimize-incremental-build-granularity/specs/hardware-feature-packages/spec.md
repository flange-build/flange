## ADDED Requirements

### Requirement: vendor component SHALL 可声明包内附加哈希输入

`vendor` component MAY 声明可选的 `inputs` 字段（相对包根的路径列表），用于登记位于 App 目录之外、但确实参与该 App 构建的包内内容（如补丁目录）。展开时 SHALL 写入 `packages_meta.app_src_paths[<app>]`，供缓存把这些路径纳入该 App 的内容哈希。`inputs` 必须是非空字符串列表，声明的路径必须存在，否则配置解析失败。

#### Scenario: 声明补丁目录为附加输入

- **WHEN** vendor component 声明 `inputs: ["patches"]` 且该目录下的补丁内容变化
- **THEN** 对应 App 的内容哈希变化并触发重建

#### Scenario: 未声明 inputs

- **WHEN** vendor component 未声明 `inputs`
- **THEN** 不登记任何附加输入，App 目录自身内容仍照常纳入哈希

#### Scenario: 声明的路径不存在

- **WHEN** `inputs` 指向包内不存在的路径
- **THEN** 配置解析失败并指出缺失路径
