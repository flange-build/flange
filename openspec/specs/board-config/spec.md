# board-config Specification

## Purpose

定义 board Jsonnet overlay 的身份字段与板级事实边界：哪些声明属于「这块板独有的硬件事实」，哪些应当上移到 SoC 或 platform 层，以及 board 目录可以携带哪些被公共 builder 自动消费的数据。
## Requirements
### Requirement: 板级配置身份

`components/board/<board>/config.jsonnet` MUST 声明与目录一致的 `board`，以及
所属 `platform`、`soc`、可用 `products` 和 `variants`。注册表 MUST 从该文件
自动发现 board，不得动态 import Python 配置模块。

#### Scenario: 自动发现 board

- **WHEN** board 目录包含合法 `config.jsonnet`
- **THEN** `discover_boards()` 返回其身份投影

#### Scenario: 身份与目录不一致

- **WHEN** `board` 字段与目录名不同
- **THEN** Jsonnet loader 在组合配置前报错

### Requirement: 板级硬件事实使用 canonical 字段

板级设备树 MUST 通过 `kernel.device_tree.name` 声明；Kconfig override MUST
使用 `kernel.config` / `bootloader.config`；运行期 overlay MUST 使用
`boot.overlays.{intree,vendor,board,package,enabled}`。不得使用任何旧 alias。

#### Scenario: 板级设备树

- **WHEN** board 声明 `kernel+: {device_tree+: {name: "demo"}}`
- **THEN** builder 从 platform/SoC 提供的 directory 和 board 提供的 name 组成路径

### Requirement: 板级数据目录

board MAY 携带 `overlay/`、`patches/` 和 `dtso/` 数据；这些内容 MUST 由公共
builder 根据 canonical 配置消费，新增 board 不得要求修改框架层代码。

#### Scenario: 新增板携带板级数据

- **WHEN** 新 board 目录下提供 `overlay/`、`patches/<组件>/` 或 `dtso/`
- **THEN** 公共 builder 按 canonical 配置消费它们，`builder/` 下无需任何改动

#### Scenario: 板级数据变化触发重建

- **WHEN** board 的 overlay、补丁或 dtso 内容变化
- **THEN** 消费它们的组件内容哈希随之变化并重建

### Requirement: 板级配置声明 rootfs 基线版本

平台无关的 rootfs 基线 SHALL 位于 `components/rootfs/config.jsonnet`。Board overlay MAY 通过 canonical rootfs 字段覆盖确有板级差异的输入，但 MUST NOT 为满足完整性而重复声明基线 URL、SHA256 或通用包集合。

#### Scenario: board 继承 rootfs 基线
- **WHEN** board overlay 未覆盖 rootfs 基线
- **THEN** 最终配置包含 `components/rootfs/config.jsonnet` 声明的基线及 SHA256

#### Scenario: board 覆盖板级固件
- **WHEN** 某 board 需要专属 firmware
- **THEN** board 只追加对应 firmware descriptor
- **AND** 其他 rootfs 基线字段保持继承值

