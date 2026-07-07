## ADDED Requirements

### Requirement: AMP 从核 console UART 按板选择并保持三方一致

AMP runtime SHALL 支持目标板按硬件引出情况选择从核 console UART。若目标板的 AMP console 不使用
默认 UART4，board 专用 AMP dts、HAL app、RT-Thread BSP/app MUST 对同一个 UART 实例、pin mux、
clock、IRQ 与 baud rate 达成一致。

对 Orange Pi CM4，AMP console MUST 使用 UART7_M2：

- dts `rockchip-amp` 使用 `SCLK_UART7` / `PCLK_UART7`
- dts `rockchip-amp.pinctrl-0` 使用 `uart7m2_xfer`
- dts `rockchip-amp.amp-irqs` 使用 `UART7_IRQn` / INTID 155 作为 console IRQ
- HAL app 使用 `UART7`、`g_uart7Dev`、`HAL_PINCTRL_IOFuncSelForUART7(IOFUNC_SEL_M2)`，
  baud rate 保持 1500000
- RT-Thread BSP/app 使用 `RT_USING_UART7`、console device `uart7`、UART7_M2 pin mux、
  `UART7_IRQn`，baud rate 保持 115200

对既有 `tspi-rk3566`，AMP console MUST 保持 UART4_M1 行为不变。

#### Scenario: Orange Pi CM4 HAL runtime 的 UART 配置一致

- **WHEN** 构建 `orangepi-cm4-amp-release`
- **THEN** board AMP dts 中 `rockchip-amp` 的 clock/pinctrl/console IRQ 指向 UART7_M2
- **AND** HAL app 初始化 UART7_M2
- **AND** HAL app baud rate 为 1500000
- **AND** HAL app 的 console IRQ 配置使用 `UART7_IRQn`

#### Scenario: Orange Pi CM4 RT-Thread runtime 的 UART 配置一致

- **WHEN** 构建 `orangepi-cm4-amp-rtt-release`
- **THEN** board AMP dts 中 `rockchip-amp` 的 clock/pinctrl/console IRQ 指向 UART7_M2
- **AND** RT-Thread app 的 `.config` 片段选择 `RT_USING_UART7`
- **AND** RT-Thread console device 为 `uart7`
- **AND** RT-Thread BSP 为 UART7_M2 配置 pin mux、board 描述与 `UART7_IRQn`
- **AND** RT-Thread UART7 baud rate 为 115200

#### Scenario: tspi-rk3566 仍保持 UART4_M1

- **WHEN** 构建或解析 `tspi-rk3566-amp-release` 与 `tspi-rk3566-amp-rtt-release`
- **THEN** 其 AMP dts、HAL app 与 RT-Thread 默认配置仍使用 UART4_M1
- **AND** 不要求 `tspi-rk3566` 切换到 UART7_M2

### Requirement: 板级 console UART 变更不改变 rpmsg 协议

AMP console UART 的板级差异 MUST NOT 改变 Linux↔AMP rpmsg 通信协议。Orange Pi CM4 的 HAL 与
RT-Thread AMP product SHALL 继续使用现有 rpmsg 约束：

- `rockchip,link-id = <0x10>`
- 从核 endpoint 名称为 `rpmsg-ap3-ch0`
- 从核 endpoint address 为 `0x3003`
- `MBOX0_CH3_A2B_IRQn` / INTID 222 路由到 cpu3
- Linux 内核 rpmsg 驱动保持 stock，不为 Orange Pi CM4 增加专用 patch

#### Scenario: Orange Pi CM4 HAL 与 RT-Thread 共用 rpmsg 协议

- **WHEN** 构建 `orangepi-cm4-amp-release` 与 `orangepi-cm4-amp-rtt-release`
- **THEN** 二者 board AMP dts 的 `rockchip,link-id` 均为 `0x10`
- **AND** 二者从核 app 均通告 endpoint `rpmsg-ap3-ch0`
- **AND** 二者从核 app 均使用 endpoint address `0x3003`
- **AND** 二者 dts 的 `amp-irqs` 均包含 `MBOX0_CH3_A2B_IRQn` / INTID 222 路由到 cpu3

#### Scenario: Orange Pi CM4 上板 rpmsg 双向 echo 成功

- **WHEN** Orange Pi CM4 启动任一 AMP product 且 Linux 侧创建匹配 `rpmsg-ap3-ch0` 的
  `/dev/rpmsgN` 端点
- **THEN** 向 `/dev/rpmsgN` 写入数据后可读回从核 echo
- **AND** Linux dmesg 显示创建对应 rpmsg channel
