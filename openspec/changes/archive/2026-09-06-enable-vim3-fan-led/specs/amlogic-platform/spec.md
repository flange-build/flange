## ADDED Requirements

### Requirement: VIM3 板载风扇与 LED 默认策略

Khadas VIM3 必须（SHALL）通过主线驱动和板级设备树覆盖实现自动温控风扇与双色 LED（发光二极管）运行指示。

#### Scenario: 冷启动自动温控

- **WHEN** 任意 VIM3 product/variant 使用默认 boot 启动
- **THEN** MCU 风扇及其 I2C、thermal 依赖内建于内核
- **AND** CPU 升温到 50/60/70°C 时分别请求 1/2/3 档，降温采用 5°C 回差，低温最终停转
- **AND** 保留上游 CPU 降频与过热保护

#### Scenario: LED 默认状态与用户控制

- **WHEN** VIM3 LED 驱动完成 probe
- **THEN** `white:status` 使用 heartbeat，`red:status` 使用 default-on
- **AND** GPIO LED、TCA6408 扩展器和上述 trigger 内建
- **AND** 用户可通过标准 LED sysfs 修改 trigger 和 brightness

#### Scenario: 板级边界与已有功能

- **WHEN** 解析 VIM3 和 VIM3L 配置
- **THEN** 仅 VIM3 默认声明并启用风扇/LED overlay
- **AND** VIM3 原有 SPI overlay 保持启用
- **AND** 不添加用户态温控服务或直接写 I2C 的脚本
