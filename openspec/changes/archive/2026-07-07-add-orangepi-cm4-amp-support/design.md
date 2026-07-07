## Context

`tspi-rk3566` 已经通过 `default` / `amp` / `amp-rtt` 三个 product 交付 AMP 支持：
`amp` 使用裸机 HAL app，`amp-rtt` 使用 RT-Thread BSP overlay app；二者共用 AMP 分区、
U-Boot AMP loader、kernel rpmsg 配置、AMP dts 与 RK3566 SoC 层的 `amp.memory`。

`orangepi-cm4` 当前只有 `default` product，默认 dts 是 `rk3566-orangepi-cm4-base`，并且
已有 WiFi/BT 固件、bcmdhd 路径、bootargs、NPU disabled 等板级修复。AMP 支持需要在不影响
default product 的前提下新增。

关键硬件差异是 Orange Pi CM4 40pin 没有引出 `tspi-rk3566` AMP demo 使用的 UART4_M1。根据
40pin mux 与 RK3568 pinctrl，Orange Pi CM4 可用的从核 console 选择为 UART7_M2：

- UART7_TX_M2 = GPIO4_A2 = 40pin 15 脚
- UART7_RX_M2 = GPIO4_A3 = 40pin 16 脚
- UART7 controller = `serial@fe6b0000`
- UART7 clock = `SCLK_UART7` / `PCLK_UART7`
- UART7 IRQ = GIC INTID 155

HAL demo 的 baud rate 保持 `1500000`，RT-Thread console baud rate 保持 `115200`。
rpmsg link-id 继续使用已验证的 `0x10`，mailbox 接收中断仍为 `MBOX0_CH3_A2B_IRQn` / INTID
222，Linux 内核 rpmsg 驱动保持 stock。

## Goals / Non-Goals

**Goals:**

- 新增 `orangepi-cm4-amp-{debug,release}`，构建并刷写 HAL AMP 固件。
- 新增 `orangepi-cm4-amp-rtt-{debug,release}`，构建并刷写 RT-Thread AMP 固件。
- Orange Pi CM4 AMP 从核 console 统一使用 UART7_M2，并在 dts、HAL app、RT-Thread BSP
  三处保持 UART 实例、pin mux、clock、IRQ 一致。
- 复用 RK3566 SoC 层 AMP 内存布局、AMP 分区顺序、U-Boot loader、rpmsg 字符设备与现有
  `RockchipAmpBuilder`。
- 保持 `orangepi-cm4-default-*` 和 `tspi-rk3566-*` 行为不变。

**Non-Goals:**

- 不做 Orange Pi CM4 DSI 屏适配。
- 不修改 stock Rockchip rpmsg 内核驱动。
- 不改变 HAL / RT-Thread demo 的 baud rate。
- 不抽象通用的任意 UART console 配置 API。
- 不改变 AMP 内存布局、rpmsg endpoint 名称、endpoint 地址或 link-id。

## Decisions

### 1. 通过 product 条件键启用 Orange Pi CM4 AMP

`components/board/orangepi-cm4/config.py` 增加 `products = ["default", "amp", "amp-rtt"]`。
实现方式对齐 `tspi-rk3566`：

- `amp.enabled:amp = True`、`amp.mode:amp = "hal"`、`amp.app:amp` 指向 Orange Pi CM4
  专用 UART7 HAL demo。
- `amp.enabled:amp-rtt = True`、`amp.mode:amp-rtt = "rt-thread"`、`amp.app:amp-rtt` 指向
  Orange Pi CM4 专用 UART7 RT-Thread demo。
- `bootloader.+defconfig:amp` / `bootloader.+defconfig:amp-rtt` 追加 `CONFIG_AMP=y` 与
  `CONFIG_ROCKCHIP_AMP=y`。
- `kernel.dts:amp` / `kernel.dts:amp-rtt` 选择同一份 Orange Pi CM4 AMP dts。
- `kernel.+defconfig:amp` / `kernel.+defconfig:amp-rtt` 追加 `CONFIG_RPMSG_CHAR=y` 与
  `CONFIG_RPMSG_CTRL=y`。
- `partitions:amp` / `partitions:amp-rtt` 使用带 `amp` ext4 分区的 product 专用分区表。

备选方案是把 AMP enable 写成 board 默认配置。该方案会污染 default product 的分区、CPU 数量与
bootloader 行为，不符合现有 product 隔离约定，因此不采用。

### 2. 使用 Orange Pi CM4 专用静态 AMP dts

新增 board kernel patch，向内核树加入 `rk3566-orangepi-cm4-amp.dts`。该 dts 由
`orangepi-cm4-amp` 和 `orangepi-cm4-amp-rtt` 两个 product 选择，default product 继续使用
`rk3566-orangepi-cm4-base`。

AMP dts 以基础板 dts 加 `rk3568-amp.dtsi` 为起点，再做 board 级 override：

- 增加 `amp@7000000` 固件代码区 reserved-memory，保持与 `amp.memory.cpu_base` / `dram_size`
  一致。
- 覆盖 `amp-cpu3.entry = 0x07000000`。
- 覆盖 `rpmsg.rockchip,link-id = <0x10>`。
- 覆盖 `rockchip_amp.clocks`，把 console UART clock 从 UART4 改为 UART7，同时保留 timer 与
  MCU clock。
- 覆盖 `rockchip_amp.pinctrl-0 = <&uart7m2_xfer>`。
- 覆盖 `rockchip_amp.amp-irqs`，把 console IRQ 从 UART4 INTID 152 改为 UART7 INTID 155，并保留
  CPUOFF、TOUCH、MBOX0_CH3_A2B INTID 222。
- 修正 `arm_pmu` affinity，只保留 cpu0/cpu1/cpu2。
- `/delete-node/ &cpu3`，把第 4 核交给 AMP 固件。

备选方案是 patch 基础 dtsi 或使用 runtime overlay。patch 基础 dtsi 会影响 default product；
runtime overlay 不是 AMP 现有路径，且 default extlinux 不应用 overlay，因此不采用。

### 3. 为 Orange Pi CM4 使用专用 UART7 AMP demo/app

HAL app 采用 `rk3568_amp_demo` 的行为副本，但 console 从 UART4_M1 切到 UART7_M2：

- `pUart = UART7`
- pin mux 设置 GPIO4_A3 / GPIO4_A2 为 func4
- 调用 `HAL_PINCTRL_IOFuncSelForUART7(IOFUNC_SEL_M2)`
- `irqsConfig[]` 中 console IRQ 使用 `UART7_IRQn`
- `HAL_UART_Init(&g_uart7Dev, ...)`
- baud rate 保持 `UART_BR_1500000`

RT-Thread app 采用现有 rpmsg echo overlay 行为，但增加 `.config` 片段选择 `uart7` 作为 console：

- `CONFIG_RT_CONSOLE_DEVICE_NAME="uart7"`
- `# CONFIG_RT_USING_UART4 is not set`
- `CONFIG_RT_USING_UART7=y`

同时需要补齐 RK3568-32 BSP 模板的 UART7 支持：

- `driver/Kconfig` 增加 `RT_USING_UART7`。
- `board/common/board_base.c` 增加 `g_uart7_board`，baud rate 为 `UART_BR_115200`，并在
  `irqsConfig[]` 中按 `RT_USING_UART7` 路由 `UART7_IRQn`。
- `board/common/iomux_base.{h,c}` 增加 `uart7_m2_iomux_config()`，并在 `RT_USING_UART7` 时调用。
- 保持现有 `RT_USING_UART4` 默认配置不变，使 `tspi-rk3566-amp-rtt` 继续使用 UART4。

备选方案是把现有 `rk3568_amp_demo` / `rk3568_amp_rtt_demo` 全局改成 UART7。该方案会破坏
`tspi-rk3566` 已验证的 UART4 行为，因此不采用。另一备选方案是在 builder 层新增通用 UART console
参数注入；当前只有 Orange Pi CM4 一个新增差异点，新增框架抽象收益不足，因此本轮不采用。

### 4. 复用既有 AMP 内存布局与 rpmsg 协议

Orange Pi CM4 与 `tspi-rk3566` 同为 RK3566，AMP 内存布局继续来自
`components/platform/rockchip/rk3566/config.py`：

- cpu3 固件：`0x07000000` / `0x00800000`
- shared memory：`0x07800000` / `0x00400000`
- Linux rpmsg：`0x07C00000` / `0x00500000`

rpmsg endpoint 继续使用 `rpmsg-ap3-ch0`、endpoint address `0x3003`、link-id `0x10`。这保证
HAL 与 RT-Thread 两个 mode 只在 console UART 与固件形态上不同，Linux 用户态通信路径不分叉。

## Risks / Trade-offs

- **Risk: UART7_M2 与板上其他外设复用冲突** → 通过 40pin mux 文档、kernel pinctrl 与实机串口日志验证；
  AMP product 文档明确占用 40pin 15/16，default product 不占用。
- **Risk: DTS 中 UART7 clock / pinctrl / IRQ 与固件不一致** → 在规格与任务中加入 dtb 反编译检查，
  并在上板验证中要求从核 console 有输出、rpmsg link-up 成功。
- **Risk: RT-Thread BSP 补 UART7 影响现有 UART4 console** → 只增加条件化 `RT_USING_UART7` 支持，
  默认 `.config` 保持 UART4；增加配置测试覆盖 `tspi-rk3566-amp-rtt`。
- **Risk: 新增 UART7 demo 与 UART4 demo 产生代码重复** → 本轮优先隔离风险；如后续更多板需要不同
  console，再单独提案做 app 参数化或共享源抽象。
- **Risk: 仅本机构建无法覆盖硬件电气接线问题** → proposal/tasks 中保留上板验证步骤，要求通过 UART7_M2
  观察 HAL 与 RT-Thread console，并验证 `/dev/rpmsg*` 双向 echo。

## Migration Plan

新增 product 不改变现有 default 镜像。用户从 `orangepi-cm4-default-*` 切到 `orangepi-cm4-amp-*`
或 `orangepi-cm4-amp-rtt-*` 时，因分区表新增 `amp` 分区，需要执行整盘刷写；回退到 default product
同样按整盘刷写恢复默认分区表。

代码回滚可以删除本 change 新增的 Orange Pi CM4 product 条件、board AMP dts patch、UART7 demo/app 与
RT-Thread UART7 BSP glue；`tspi-rk3566` 不需要迁移。

## Open Questions

无阻塞性问题。实施阶段仍需在 Orange Pi CM4 实机上确认 UART7_M2 电平、接线方向与 console 输出。
