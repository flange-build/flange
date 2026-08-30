## ADDED Requirements

### Requirement: 板级配置声明 rootfs 基线版本

平台无关的 rootfs 基线 SHALL 位于 `components/rootfs/config.jsonnet`。Board overlay MAY 通过 canonical rootfs 字段覆盖确有板级差异的输入，但 MUST NOT 为满足完整性而重复声明基线 URL、SHA256 或通用包集合。

#### Scenario: board 继承 rootfs 基线
- **WHEN** board overlay 未覆盖 rootfs 基线
- **THEN** 最终配置包含 `components/rootfs/config.jsonnet` 声明的基线及 SHA256

#### Scenario: board 覆盖板级固件
- **WHEN** 某 board 需要专属 firmware
- **THEN** board 只追加对应 firmware descriptor
- **AND** 其他 rootfs 基线字段保持继承值
