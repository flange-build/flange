## Context

Linux v6.12 `meson-khadas-vim3.dtsi` 已描述 I2C AO 上 0x18 的 MCU 风扇、0x20 的 TCA6408 红灯 GPIO5，以及 GPIOAO_4 白灯。`khadas_mcu_fan.c` 提供 0–3 档 thermal cooling device（散热设备）；现有 CPU active trip（主动散热温度点）为 80°C，白灯默认为 heartbeat，红灯无默认 trigger。

## Goals / Non-Goals

目标：VIM3 四个 target 默认自动温控并点亮双色运行指示，保留标准 sysfs 控制。
非目标：用户态风扇守护进程、硬编码 I2C 总线号、VIM3L 策略修改、转速 RPM 反馈。

## Decisions

- 在 VIM3 board 的 `kernel.config` 显式内建 MCU、风扇、I2C、GPIO 扩展器、LED 和 thermal step_wise 依赖，启动不依赖 rootfs 模块加载。
- 新增一个默认加载的板级 overlay。复用 `cpu-active` 节点改为 50°C/5°C 回差，把其现有 `map` 改为固定 1 档，再添加 60°C/2 档、70°C/3 档及相同回差。固定上下限避免 step_wise 在低温档持续升档；原 CPU 降频映射及保护节点保留。阈值留在 overlay 中，可按实际散热器与噪声需求调整。
- 白灯使用 `heartbeat`，红灯 `default-on`，沿用已有 GPIO 定义和 `white:status` / `red:status` 名称。通过标准 trigger / brightness 操作，不增加脚本或服务。

## Risks / Trade-offs

- 三档阈值是本项目默认策略，实际起转、噪声和温度稳定性依赖风扇、机壳与 MCU 固件，需实板验收。
- 主线接口是 `/sys/class/thermal/`，不是 Khadas 下游的 `/sys/class/fan/`；文档明确区分。
- overlay 按主线 v6.12 节点路径合并，验证时必须实际应用到 DTB，确认保留保护节点及 SPI overlay 共存。

## Migration Plan

重建并部署 boot（Image、DTB 和 overlay）。如需恢复上游行为，从默认 overlay 列表移除本 overlay 并重建 boot；内建驱动可保留。
