# config-deep-merge Specification

## Purpose

保留配置组合能力的历史 capability 名称；当前实现由 Jsonnet 原生语义承担，
不再存在 Python merge API。
## Requirements
### Requirement: Jsonnet 对象组合

配置 MUST 先按 rootfs → platform → SoC → board 的固定顺序组合；随后 MUST 按 board 首次求值所得顶层 packages 顺序追加包内可选 config.jsonnet。普通字段使用后层覆盖，嵌套对象或数组追加使用 `+:`，最终 JSON 不得保留操作字段。包配置新增 packages 不触发递归加载。

#### Scenario: 嵌套对象追加
- **WHEN** board 使用 `kernel+: {config+: {CONFIG_FOO: "y"}}`
- **THEN** 最终 `kernel.config.CONFIG_FOO == "y"`，且上层其他 kernel 字段保留

#### Scenario: package config 在 board 后追加
- **WHEN** board 选择含 config.jsonnet 的 package
- **THEN** package 通过 rootfs+: 追加并保留已有字段，配置文件进入求值依赖集合

#### Scenario: package config 不递归选择 package
- **WHEN** 已选 package 的 config.jsonnet 追加另一包名
- **THEN** 不递归加载后追加包的 config.jsonnet

### Requirement: 数组增减

数组增加 MUST 使用 Jsonnet `+` 或字段 `+:`；删除标量元素 MUST 使用
`components/config/lib.libsonnet` 的 `without(values, removed)`，并保持未删除
元素的顺序与重复项。

#### Scenario: 删除并追加 defconfig

- **WHEN** 下层对上层 defconfig 调用 `without` 后追加一个 fragment
- **THEN** 最终 JSON 只包含运算后的 defconfig 数组

### Requirement: product 与 variant 条件

product/variant 条件 MUST 通过 Jsonnet std.extVar 和 if 求值，最终不得保留未求值维度子树或私有条件后缀。
结构维度只在顶层身份字段出现；显式动态名称映射中与 product/variant 同名的合法资源 MUST 按该映射 schema 校验，不得被全局字符串扫描误拒绝。

#### Scenario: debug 数组追加
- **WHEN** variant 为 debug
- **THEN** Jsonnet 追加 debug 包，builder 只看到最终数组

#### Scenario: source 名为 product
- **WHEN** sources.product 声明合法仓库来源
- **THEN** 不将其解释为 product 条件子树
