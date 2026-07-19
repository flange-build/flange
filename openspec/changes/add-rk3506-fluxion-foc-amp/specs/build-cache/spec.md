## ADDED Requirements

### Requirement: OOT 本地应用必须级联失效

当 app 或 amp 组件消费 local_path/external_app_dirs 源时，缓存 SHALL 禁止该组件命中旧
产物，并沿既有依赖图使所有下游组件失效。

#### Scenario: OOT Linux bridge 变化

- **WHEN** 本地 bridge 源码变化且 image 依赖 app→rootfs
- **THEN** app、rootfs 和 image 均不得复用变化前的构建结果
