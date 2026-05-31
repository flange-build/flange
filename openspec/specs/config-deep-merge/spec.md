# config-deep-merge Specification

## Purpose
TBD - created by archiving change 2026-03-29-phase2-config-system. Update Purpose after archive.
## Requirements
### Requirement: deep_merge 函数合并两个 dict
`build/deep_merge.bzl` SHALL 提供 `deep_merge(base, override)` 函数，接受两个 dict 参数，返回深度合并后的新 dict。合并规则：dict 类型递归合并，非 dict 类型后者覆盖前者，`base` 中存在但 `override` 中不存在的 key 保留。

#### Scenario: 嵌套 dict 递归合并
- **WHEN** 调用 `deep_merge({"a": {"x": 1, "y": 2}}, {"a": {"y": 3, "z": 4}})`
- **THEN** 返回 `{"a": {"x": 1, "y": 3, "z": 4}}`

#### Scenario: 非 dict 值直接覆盖
- **WHEN** 调用 `deep_merge({"a": [1, 2]}, {"a": [3]})`
- **THEN** 返回 `{"a": [3]}`（列表替换，不追加）

#### Scenario: base 独有 key 保留
- **WHEN** 调用 `deep_merge({"a": 1, "b": 2}, {"a": 10})`
- **THEN** 返回 `{"a": 10, "b": 2}`

### Requirement: deep_merge 不修改输入 dict
`deep_merge` 函数 SHALL NOT 修改传入的 `base` 或 `override` dict，MUST 返回全新的 dict 对象。

#### Scenario: 原始 dict 不被修改
- **WHEN** 定义 `base = {"a": {"x": 1}}` 并调用 `deep_merge(base, {"a": {"y": 2}})`
- **THEN** 调用后 `base` 仍为 `{"a": {"x": 1}}`

