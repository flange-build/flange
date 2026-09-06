## MODIFIED Requirements

### Requirement: 缓存命中测试 MUST 同时验证哈希与必需产物

缓存正向测试 MUST 创建 TaskPlan 声明的必需产物，通过 `TaskPlan.fingerprint()` 获取输入身份，并由 `BuildCache.store(plan, before, dependencies)` 发布成功 ArtifactManifest。命中判断 MUST 同时验证输入和每项输出的内容、权限、节点类型与链接目标；测试不得依赖旧 hash 标记或已删除的私有 helper。

#### Scenario: 缺少必需产物
- **WHEN** 测试没有创建声明的 modules、镜像或 deb
- **THEN** 成功发布被拒绝，不能构造仅有输入摘要的假命中

#### Scenario: 源码变化后查询
- **WHEN** 测试修改具名源码输入
- **THEN** 使用同一公开计划重新计算指纹或重新构造计划后查询，观察到输入变化和缓存 miss

#### Scenario: 已发布产物损坏
- **WHEN** 成功 manifest 已存在，但产物被删除或权限改变
- **THEN** BuildCache.explain 返回 miss 并指出受影响的产物
