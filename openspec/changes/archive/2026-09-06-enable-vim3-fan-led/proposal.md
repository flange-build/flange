## Why

Khadas VIM3 的主线设备树已有风扇与双色 LED（发光二极管），但风扇默认到 80°C 才启动，板级配置未明确保证驱动与灯效。需要交付启动即生效的温控和可辨识的运行指示。

## What Changes

- VIM3 内建 MCU（微控制器）风扇、温控和 GPIO LED 依赖。
- 板级 overlay（设备树覆盖）将风扇设为 50/60/70°C 三档、5°C 回差，白灯心跳、红灯常亮。
- 保留上游 CPU 降频和过热保护，提供主线 sysfs（系统文件接口）操作与验收说明。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `amlogic-platform`：增加 VIM3 风扇与 LED 的板级运行契约。

## Impact

仅 VIM3 板级配置、一个 DT overlay、配置回归测试和板卡文档；复用主线驱动及已有构建流程。

## 非目标

不改 VIM3L 默认行为，不引入用户态轮询服务、直接 I2C 寄存器写入或 Khadas 下游内核接口；未连接实板时不宣称硬件验收完成。
