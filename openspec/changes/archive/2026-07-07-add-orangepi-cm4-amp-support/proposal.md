## Why

`tspi-rk3566` 已经有 `amp` 与 `amp-rtt` product，可用于验证 Rockchip RK356x AMP（Asymmetric
Multi-Processing，非对称多处理）HAL 与 RT-Thread 从核固件；`orangepi-cm4` 目前缺少同等能力。

Orange Pi CM4 40pin 引脚没有引出当前 AMP demo 使用的 UART4_M1，但引出了 UART7_M2。若直接复用
`tspi-rk3566` 的 UART4 方案，从核 console 无法通过 40pin 接出，不利于 bring-up、日志观察与故障定位。

## What Changes

- 为 `orangepi-cm4` 新增 `amp` product，启用 HAL 模式 AMP 固件、AMP 分区、AMP bootloader 选项与
  对应 kernel dts。
- 为 `orangepi-cm4` 新增 `amp-rtt` product，启用 RT-Thread 模式 AMP 固件，并复用同一套板级 AMP
  dts 与分区布局。
- Orange Pi CM4 的 AMP 从核 console 使用 40pin 可引出的 UART7_M2：
  - 40pin 15 脚：GPIO4_A2 / UART7_TX_M2
  - 40pin 16 脚：GPIO4_A3 / UART7_RX_M2
- 保持现有波特率不变：
  - HAL demo 继续使用 1500000
  - RT-Thread demo 继续使用 115200
- 保持 `tspi-rk3566` 既有 AMP product 行为不变，不把 UART7_M2 变更扩散到已有 UART4_M1 demo。
- 补齐 Orange Pi CM4 AMP 相关测试与文档，尤其说明 UART7_M2 选型、40pin 接线、AMP 内存布局与现有
  `docs/amp.md` 中内存地址描述的差异。

## 非目标

- 不启用或适配 Orange Pi CM4 DSI 屏幕链路。
- 不修改 `orangepi-cm4-default-*` product 的默认启动行为、CPU 数量、分区布局或 WiFi/BT/NPU 相关修复。
- 不改变 `tspi-rk3566-amp-*` 与 `tspi-rk3566-amp-rtt-*` 的 UART4_M1 console、波特率、link-id 或
  rpmsg 行为。
- 不引入通用化的任意 UART console 配置框架；本 change 只交付 Orange Pi CM4 所需的 UART7_M2 支持。
- 不改动 stock Rockchip rpmsg 内核驱动，不改变现有 `amp` 分区刷写协议。
- 不覆盖 OTA、A/B、recovery 自升级或量产校准流程。

## Capabilities

### New Capabilities

- 无。

### Modified Capabilities

- `rockchip-orangepi-cm4`：新增 Orange Pi CM4 的 `amp` / `amp-rtt` product 行为要求，并规定 AMP
  console 使用 UART7_M2 引出到 40pin。
- `amp-runtime-bringup`：补充 AMP 运行时允许按板选择从核 console UART、pin mux、clock 与 IRQ 的要求；
  现有默认 UART4 行为仍适用于 `tspi-rk3566`。

## Impact

- `components/board/orangepi-cm4/config.py`：新增 `amp` / `amp-rtt` product 条件配置、AMP 分区与
  bootloader/kernel/rootfs 追加项。
- `components/board/orangepi-cm4/patches/kernel/`：新增 Orange Pi CM4 专用 AMP dts patch，覆盖
  UART7_M2 pinctrl、UART7 clock、UART7 IRQ、AMP reserved-memory、cpu3 摘除与 rpmsg mailbox 配置。
- `components/app/`：新增或拆分 Orange Pi CM4 专用 UART7 HAL/RT-Thread AMP demo，避免影响已有 UART4
  demo。
- `components/platform/rockchip/rt-thread/`：补齐 RK3568 32-bit BSP 的 UART7_M2 board glue，使
  RT-Thread console 可选择 `uart7`。
- `builder/config/validate.py` 及配置查询测试：增加 Orange Pi CM4 AMP product 的配置校验覆盖。
- `docs/amp.md` 与 Orange Pi CM4 板级文档：补充 UART7_M2 接线、产品选择与内存布局说明。
