## ADDED Requirements

### Requirement: 平台声明额外产物与依赖
平台契约 MUST 允许策略声明组件的必需产物与附加依赖；执行、计划、缓存和发布 MUST 消费相同声明。
未声明的平台 MUST 保持现有行为；错误依赖、循环和重复产物 MUST 明确拒绝。

#### Scenario: 平台 boot 依赖 rootfs
- **WHEN** 平台声明 boot 需要 rootfs 提供 initrd
- **THEN** 构建顺序和 boot 指纹均包含 rootfs，独立 boot 构建也满足该依赖

#### Scenario: 平台发布额外目录
- **WHEN** 平台声明 bootloader 的 firmware 目录及必需 Firehose loader
- **THEN** 缺失任一必需输出时禁止发布成功或命中有效缓存

#### Scenario: 原平台未声明
- **WHEN** 构建既有平台且没有额外声明
- **THEN** 其组件依赖与必需输出集合保持不变
