## 1. Board 配置

- [x] 1.1 在 `components/board/orangepi-cm4/config.py` 增加 `default` / `amp` / `amp-rtt` product 列表。
- [x] 1.2 为 `orangepi-cm4-amp` 增加 HAL AMP 条件配置：`amp.enabled`、`amp.mode=hal`、UART7 HAL app、AMP dts、bootloader/kernel defconfig 与 AMP 分区表。
- [x] 1.3 为 `orangepi-cm4-amp-rtt` 增加 RT-Thread AMP 条件配置：`amp.enabled`、`amp.mode=rt-thread`、UART7 RT-Thread app、同一 AMP dts、bootloader/kernel defconfig 与 AMP 分区表。
- [x] 1.4 增加或更新配置解析测试，覆盖 `orangepi-cm4-default-*` 不含 AMP、两个 AMP product 配置正确、`tspi-rk3566-*` 行为不变。

## 2. Kernel AMP DTS

- [x] 2.1 新增 Orange Pi CM4 board kernel patch，添加 `rk3566-orangepi-cm4-amp.dts`。
- [x] 2.2 在 AMP dts 中接入 `rk3568-amp.dtsi`，补齐固件 reserved-memory、`amp-cpu3.entry=0x07000000`、`rockchip,link-id=<0x10>`、`arm_pmu` 三核 affinity 与 `/delete-node/ &cpu3`。
- [x] 2.3 在 AMP dts 中把 `rockchip_amp` console 从 UART4_M1 覆盖为 UART7_M2：`SCLK_UART7` / `PCLK_UART7`、`uart7m2_xfer`、`UART7_IRQn` / INTID 155，并保留 CPUOFF、TOUCH、MBOX0_CH3_A2B / INTID 222。
- [x] 2.4 构建或反编译 dtb，确认 Orange Pi CM4 AMP dtb 含 AMP 节点、UART7_M2 配置、cpu3 摘除、rpmsg link-id 0x10。

## 3. HAL AMP App

- [x] 3.1 新增 Orange Pi CM4 专用 UART7 HAL AMP app，复用 `rk3568_amp_demo` 的 rpmsg echo 行为。
- [x] 3.2 将 HAL app console 切到 UART7_M2：`UART7`、`g_uart7Dev`、GPIO4_A2/A3 func4、`HAL_PINCTRL_IOFuncSelForUART7(IOFUNC_SEL_M2)`、`UART7_IRQn`。
- [x] 3.3 确认 HAL app baud rate 保持 `UART_BR_1500000`，endpoint 名称、endpoint 地址、link-id 与 echo 行为不变。

## 4. RT-Thread AMP App 与 BSP

- [x] 4.1 在 RK3568-32 RT-Thread BSP 模板中补 `RT_USING_UART7` Kconfig 选项。
- [x] 4.2 在 BSP `board_base.c` 中增加 `g_uart7_board`，baud rate 为 `UART_BR_115200`，并按 `RT_USING_UART7` 路由 `UART7_IRQn` 到 cpu3。
- [x] 4.3 在 BSP `iomux_base.{h,c}` 中增加 `uart7_m2_iomux_config()`，并在 `RT_USING_UART7` 时配置 GPIO4_A2/A3 func4 与 `IOFUNC_SEL_M2`。
- [x] 4.4 新增 Orange Pi CM4 专用 UART7 RT-Thread AMP app，复用现有 rpmsg echo overlay 行为并添加 `.config` 片段选择 `uart7` console。
- [x] 4.5 确认 RT-Thread app 保持 link-id 0x10、endpoint `rpmsg-ap3-ch0`、endpoint address `0x3003` 与 MBOX0_CH3_A2B 白名单补丁逻辑不变。

## 5. 文档

- [x] 5.1 更新 `docs/amp.md`，修正当前 RK3566 AMP 内存布局描述，避免继续引用旧的 `0x02800000` 固件地址。
- [x] 5.2 更新 Orange Pi CM4 板级文档，说明 `amp` / `amp-rtt` product、UART7_M2 40pin 接线、HAL/RT-Thread baud rate 与整盘刷写要求。

## 6. 验证

- [x] 6.1 运行 `openspec validate add-orangepi-cm4-amp-support --strict`。
- [x] 6.2 运行配置相关 Python 测试，至少覆盖配置查询、registry 与 validate 测试。
- [x] 6.3 构建 `orangepi-cm4-amp-release` 的 `amp` 与 `kernel` 组件，确认产出 `amp.img` 与 AMP dtb。
- [x] 6.4 构建 `orangepi-cm4-amp-rtt-release` 的 `amp` 与 `kernel` 组件，确认产出 `amp.img` 与同一 AMP dtb。
- [x] 6.5 回归构建或解析 `tspi-rk3566-amp-release` 与 `tspi-rk3566-amp-rtt-release`，确认仍使用 UART4_M1。
- [x] 6.6 上板验证 `orangepi-cm4-amp-release`：UART7_M2 以 1500000 baud 输出 HAL 日志，Linux `/dev/rpmsg*` echo 成功。
- [x] 6.7 上板验证 `orangepi-cm4-amp-rtt-release`：UART7_M2 以 115200 baud 输出 RT-Thread 日志，Linux `/dev/rpmsg*` echo 成功。
