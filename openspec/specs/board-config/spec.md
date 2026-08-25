# board-config Specification

## Purpose

定义 board Jsonnet overlay 的身份字段和板级事实边界。

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
