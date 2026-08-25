## REMOVED Requirements

### Requirement: deep_merge 函数合并两个 dict

**Reason**: 配置组合改由 Jsonnet 对象继承、字段 `+:` 和显式数组表达式完成；Python `deep_merge` 无法表达统一的增减与条件语义，并导致私有操作符扩散。

**Migration**: 将普通覆盖改为 Jsonnet 对象覆盖，将嵌套对象或数组追加改为 `+:`，将数组删除改为 `without` 或按稳定身份字段的 comprehension；最终只 manifest canonical JSON。

### Requirement: deep_merge 不修改输入 dict

**Reason**: 配置系统不再公开或调用 Python `deep_merge`；Jsonnet 值本身不可变，求值结果由 evaluator 新建为 plain JSON。

**Migration**: 需要复用配置的层级改为 Jsonnet overlay，不在 Python 中传递并修改中间 dict。
