## ADDED Requirements

### Requirement: 仓库收尾 SHALL 通过完整自动化质量门禁

准备归档并声明变更完成前，flange 仓库 SHALL 在受支持的 Python 环境中运行完整 pytest，且 SHALL 运行 `openspec validate --all --strict`；两项命令都必须零失败。不得通过删除有效测试、无依据增加 `skip` 或关闭 strict 校验来达成门禁。

#### Scenario: 完整质量门禁通过

- **WHEN** 一个变更准备归档并执行最终验收
- **THEN** 完整 pytest 报告零 failed，且 OpenSpec all strict 报告全部通过

#### Scenario: 既有测试与当前公开契约不一致

- **WHEN** 测试仍调用已删除的私有接口、使用废弃路径或断言已正式变更的配置默认值
- **THEN** 维护者依据当前主规格和公开接口同步测试，并保留其行为覆盖，不得仅因测试陈旧而删除用例

### Requirement: 缓存命中测试 MUST 同时验证哈希与必需产物

对 `BuildCache.is_up_to_date()` 的正向测试 MUST 创建与目标组件匹配的最小必需产物，并保存对应内容哈希。测试 SHALL 通过公开哈希接口构造预期状态，不得依赖已删除的私有 helper。

#### Scenario: 哈希一致但必需产物缺失

- **WHEN** 测试已保存组件哈希但未创建该组件要求的产物
- **THEN** `is_up_to_date()` 返回 false，测试不得把该状态误判为 cache hit

#### Scenario: 源码变化后重新计算公开哈希

- **WHEN** 测试修改 App 或 rootfs customize 的哈希输入
- **THEN** 测试使用新的构建缓存上下文重新调用公开哈希接口，并观察到哈希变化

### Requirement: 环境能力限制 MUST 与功能回归分开验证

依赖本机回环 socket 等普通宿主能力的测试若在受限沙箱中因系统权限返回 `EPERM`，MUST 在具备该能力的普通宿主环境中复跑。只有普通宿主环境仍失败时，才 SHALL 将其判定为功能回归。

#### Scenario: 沙箱禁止回环 socket

- **WHEN** `recoveryctl` socket 测试在受限沙箱绑定 `127.0.0.1` 时返回 `EPERM`
- **THEN** 同一测试在普通宿主权限下复跑，并以该结果判定功能是否正常

#### Scenario: 普通宿主环境仍失败

- **WHEN** 受限环境失败的用例在具备所需能力的宿主环境中仍然失败
- **THEN** 质量门禁保持失败，维护者必须修复实现或测试契约后再收尾
