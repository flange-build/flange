# config-deep-merge Specification

## Purpose

保留配置组合能力的历史 capability 名称；当前实现由 Jsonnet 原生语义承担，
不再存在 Python merge API。

## Requirements

### Requirement: Jsonnet 对象组合

配置 MUST 按 rootfs → platform → SoC → board 的固定顺序组合。普通字段使用
Jsonnet 后层覆盖，嵌套对象或数组追加使用 `+:`，不得在 manifest 后的 JSON
中保留操作字段。

#### Scenario: 嵌套对象追加

- **WHEN** board 使用 `kernel+: {config+: {FOO: "y"}}`
- **THEN** 最终 `kernel.config.FOO == "y"` 且上层 kernel 字段仍保留

### Requirement: 数组增减

数组增加 MUST 使用 Jsonnet `+` 或字段 `+:`；删除标量元素 MUST 使用
`components/config/lib.libsonnet` 的 `without(values, removed)`，并保持未删除
元素的顺序与重复项。

#### Scenario: 删除并追加 defconfig

- **WHEN** 下层对上层 defconfig 调用 `without` 后追加一个 fragment
- **THEN** 最终 JSON 只包含运算后的 defconfig 数组

### Requirement: product 与 variant 条件

product/variant 条件 MUST 使用 Jsonnet `std.extVar` 和 `if` 求值。最终 JSON
只允许顶层 identity 字段 `product`、`variant`，不得携带嵌套条件子树或私有
后缀键。

#### Scenario: debug 数组追加

- **WHEN** variant 为 `debug`
- **THEN** Jsonnet 条件表达式追加 debug 包，builder 只看到最终 packages 数组
