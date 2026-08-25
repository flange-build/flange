## MODIFIED Requirements

### Requirement: 板级配置文件声明完整构建参数

`components/board/<board>/config.jsonnet` SHALL 声明 board overlay，而不是复制完整构建配置。Overlay MUST 包含 `board`、`soc`、`platform` 身份字段，并 MUST 只声明该板事实、产品列表以及对 canonical 配置的板级覆盖；Kernel/Bootloader 源码等 SoC 公共输入 MUST 由继承层提供，除非该板确实使用不同硬件来源。

#### Scenario: 板级配置包含核心身份字段
- **WHEN** 求值任一 board overlay 的身份投影
- **THEN** 包含与目录和注册表一致的 `board`、`soc`、`platform`

#### Scenario: 板级设备树覆盖使用 canonical 字段
- **WHEN** board 选择具体设备树
- **THEN** 使用 `kernel.device_tree.name`
- **AND** 不声明 `kernel.dts` 或 `kernel.dtb`

#### Scenario: 公共源码由 SoC 继承
- **WHEN** board 与同 SoC 其他 board 使用相同 Kernel 源码
- **THEN** board overlay 不重复声明 source descriptor
- **AND** 最终配置从 SoC overlay 继承该 source

### Requirement: 板级配置声明 rootfs 基线版本

平台无关的 rootfs 基线 SHALL 位于 `components/rootfs/config.jsonnet`。Board overlay MAY 通过 canonical rootfs 字段覆盖确有板级差异的输入，但 MUST NOT 为满足完整性而重复声明基线 URL、SHA256 或通用包集合。

#### Scenario: board 继承 rootfs 基线
- **WHEN** board overlay 未覆盖 rootfs 基线
- **THEN** 最终配置包含 `components/rootfs/config.jsonnet` 声明的基线及 SHA256

#### Scenario: board 覆盖板级固件
- **WHEN** 某 board 需要专属 firmware
- **THEN** board 只追加对应 firmware descriptor
- **AND** 其他 rootfs 基线字段保持继承值
