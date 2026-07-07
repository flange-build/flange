## ADDED Requirements

### Requirement: orangepi-cm4 提供 HAL 与 RT-Thread AMP product

`orangepi-cm4` board 配置 MUST 声明 `default`、`amp`、`amp-rtt` 三个 product。`amp` product SHALL
启用 HAL 模式 AMP 固件；`amp-rtt` product SHALL 启用 RT-Thread 模式 AMP 固件。两个 AMP product
MUST 复用 RK3566 SoC 层的 `amp.memory`，并 MUST 使用 product 作用域配置启用 AMP，不能改变
`default` product 的 dts、分区表、bootloader AMP 选项或 CPU 数量。

两个 AMP product MUST 满足以下配置约束：

- `amp.enabled` 为 `true`
- `amp.mode` 分别为 `hal` / `rt-thread`
- `amp.app` 分别指向 Orange Pi CM4 专用 UART7 HAL / RT-Thread AMP app
- `bootloader.defconfig` 追加 `CONFIG_AMP=y` 与 `CONFIG_ROCKCHIP_AMP=y`
- `kernel.defconfig` 追加 `CONFIG_RPMSG_CHAR=y` 与 `CONFIG_RPMSG_CTRL=y`
- `kernel.dts` 选择 Orange Pi CM4 专用 AMP dts
- `partitions` 在 `recovery` 与 `rootfs` 之间包含非 raw 的 `amp` ext4 分区，且 `rootfs` 仍为
  `remaining`

#### Scenario: HAL AMP product 配置解析正确

- **WHEN** 解析 `orangepi-cm4-amp-release` 的 FINAL_CONFIG
- **THEN** `amp.enabled` 为 `true`
- **AND** `amp.mode` 为 `hal`
- **AND** `amp.app` 指向 Orange Pi CM4 专用 UART7 HAL AMP app
- **AND** `kernel.dts` 为 Orange Pi CM4 专用 AMP dts
- **AND** `bootloader.defconfig` 同时包含 `CONFIG_AMP=y` 与 `CONFIG_ROCKCHIP_AMP=y`
- **AND** `kernel.defconfig` 同时包含 `CONFIG_RPMSG_CHAR=y` 与 `CONFIG_RPMSG_CTRL=y`
- **AND** `partitions.entries` 中 `amp` 分区位于 `recovery` 之后、`rootfs` 之前

#### Scenario: RT-Thread AMP product 配置解析正确

- **WHEN** 解析 `orangepi-cm4-amp-rtt-release` 的 FINAL_CONFIG
- **THEN** `amp.enabled` 为 `true`
- **AND** `amp.mode` 为 `rt-thread`
- **AND** `amp.app` 指向 Orange Pi CM4 专用 UART7 RT-Thread AMP app
- **AND** `kernel.dts` 与 HAL AMP product 相同
- **AND** `bootloader.defconfig` 同时包含 `CONFIG_AMP=y` 与 `CONFIG_ROCKCHIP_AMP=y`
- **AND** `kernel.defconfig` 同时包含 `CONFIG_RPMSG_CHAR=y` 与 `CONFIG_RPMSG_CTRL=y`
- **AND** `partitions.entries` 中 `amp` 分区位于 `recovery` 之后、`rootfs` 之前

#### Scenario: default product 不受 AMP product 影响

- **WHEN** 解析 `orangepi-cm4-default-release` 的 FINAL_CONFIG
- **THEN** `amp.enabled` 不为 `true`
- **AND** `kernel.dts` 仍为 `rk3566-orangepi-cm4-base`
- **AND** `bootloader.defconfig` 不包含 `CONFIG_AMP=y` 或 `CONFIG_ROCKCHIP_AMP=y`
- **AND** `partitions.entries` 不包含 `amp` 分区

### Requirement: orangepi-cm4 AMP 从核 console 使用 40pin UART7_M2

Orange Pi CM4 AMP product 的从核 console MUST 使用 UART7_M2，而不是 RK356x AMP demo 默认的
UART4_M1。板级文档 MUST 说明 UART7_M2 的 40pin 接线：

- 40pin 15 脚：GPIO4_A2 / UART7_TX_M2
- 40pin 16 脚：GPIO4_A3 / UART7_RX_M2

Orange Pi CM4 专用 AMP dts MUST 把 `rockchip-amp` 的 console 相关 clock、pinctrl 与 IRQ 切到
UART7：

- clock 使用 `SCLK_UART7` / `PCLK_UART7`
- pinctrl 使用 `uart7m2_xfer`
- console IRQ 使用 `UART7_IRQn` / GIC INTID 155

HAL AMP app MUST 初始化 UART7_M2，baud rate MUST 保持 1500000。RT-Thread AMP app/BSP MUST
初始化 UART7_M2，console device MUST 为 `uart7`，baud rate MUST 保持 115200。

#### Scenario: 编出的 AMP dtb 选择 UART7_M2

- **WHEN** 构建 `orangepi-cm4-amp-release` 或 `orangepi-cm4-amp-rtt-release` 的 kernel 并反编译 dtb
- **THEN** `rockchip-amp` 的 clock 引用包含 `SCLK_UART7` 与 `PCLK_UART7`
- **AND** `rockchip-amp` 的 `pinctrl-0` 引用 `uart7m2_xfer`
- **AND** `rockchip-amp.amp-irqs` 包含 `UART7_IRQn` / INTID 155 路由到 cpu3
- **AND** `rockchip-amp.amp-irqs` 仍包含 `MBOX0_CH3_A2B_IRQn` / INTID 222 路由到 cpu3

#### Scenario: HAL AMP 从核通过 UART7_M2 输出日志

- **WHEN** 刷写并启动 `orangepi-cm4-amp-release`，并把 USB-TTL 接到 40pin 15/16
- **THEN** 从核 console 以 1500000 baud 输出 HAL AMP 启动日志
- **AND** 日志显示 rpmsg link-up 与 endpoint announce 成功

#### Scenario: RT-Thread AMP 从核通过 UART7_M2 输出日志

- **WHEN** 刷写并启动 `orangepi-cm4-amp-rtt-release`，并把 USB-TTL 接到 40pin 15/16
- **THEN** 从核 console 以 115200 baud 输出 RT-Thread AMP 启动日志
- **AND** 日志显示 rpmsg link-up 与 endpoint announce 成功
