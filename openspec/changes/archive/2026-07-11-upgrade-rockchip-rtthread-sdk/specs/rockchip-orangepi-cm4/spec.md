## ADDED Requirements

### Requirement: Orange Pi CM4 RT-Thread AMP 独占 UART7_M2 pinmux

`rk3568_amp_uart7_rtt_demo` 的 app `.config` MUST 显式关闭 `RT_USING_GMAC1`，因为
RK3568 GMAC1_M1 与 UART7_M2 共用 GPIO4_A2/A3，且 BSP 的 GMAC1 pinmux 初始化发生在
UART7 之后。app `.config` 还 MUST 关闭 `RT_USING_UART2`，避免 AMP 初始化 Linux
debug console。该约束 MUST 由配置回归测试覆盖，不能只依赖当前 BSP 默认值。

#### Scenario: 最终 iomux 不覆盖 UART7

- **WHEN** 构建 `orangepi-cm4-amp-rtt-debug`
- **THEN** 最终 `.config` 含 `# CONFIG_RT_USING_GMAC1 is not set`
- **AND** 最终 `.config` 含 `# CONFIG_RT_USING_UART2 is not set`
- **AND** `rt_hw_iomux_config` 在配置 UART7_M2 后不调用 GMAC1_M1 pinmux

#### Scenario: UART7 从复位开始输出

- **WHEN** 刷写并重启 Orange Pi CM4 RT-Thread AMP product
- **THEN** UART7_M2 在 Linux 应用 `uart7m2_xfer` 之前已可输出
- **AND** 能看到标准 RT-Thread banner、版本与 `cpu3 up` 日志
