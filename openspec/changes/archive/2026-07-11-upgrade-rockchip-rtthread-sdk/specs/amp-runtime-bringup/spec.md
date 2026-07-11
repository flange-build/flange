## ADDED Requirements

### Requirement: RT-Thread AMP 保持单核运行并提供早期启动日志

RK3568 RT-Thread AMP SHALL 作为 cpu3 上的单核 RTOS 实例运行，MUST NOT 启用
`RT_USING_SMP` 或尝试通过 PSCI 拉起 Linux 所属 CPU。UART console 驱动 SHALL 在
device open/close 生命周期向 Rockchip UART 底层发送当前 SDK 对应的
`RT_DEVICE_CTRL_OPEN/CLOSE` 通知。

标准 RT-Thread banner/version 与 app 的 cpu 启动日志 MUST 在 RPMsg link-up 之前通过
板级 AMP console 输出；MSH 启动后手工执行 `version` 成功不能替代该早期日志验收。

#### Scenario: 启动阶段输出完整且顺序正确

- **WHEN** 刷写并冷启动 RK3568 RT-Thread AMP product
- **THEN** console 先输出 RT-Thread banner、版本和 app cpu 启动日志
- **AND** 随后输出 RPMsg remote init、link-up 与 endpoint announce
- **AND** MSH 可交互

#### Scenario: 最终固件不包含 SMP 拉核行为

- **WHEN** 检查最终 `.config` 并启动固件
- **THEN** `RT_USING_SMP` 未启用
- **AND** RT-Thread 不尝试启动 cpu0、cpu1 或 cpu2

### Requirement: RT-Thread 4.1.1 rpmsg 与中断 glue 使用当前 API

RT-Thread AMP app 调用 `rpmsg_lite_wait_for_link_up` 时 SHALL 显式传入 `RL_BLOCK`。
RK3568 rpmsg platform 的中断路由 SHALL 使用当前 HAL GIC route API，并保持既有
MBOX0_CH3_A2B IRQ、link-id 0x10 和 GIC 白名单约束不变。

#### Scenario: RT-Thread 4.1.1 构建并完成 RPMsg echo

- **WHEN** 使用同步后的 RT-Thread 4.1.1 与 Rockchip HAL SDK 构建并上板
- **THEN** app 不因旧版 rpmsg-lite 或 GIC route API 编译失败
- **AND** Linux 创建 `rpmsg-ap3-ch0` 后双向 echo 成功
