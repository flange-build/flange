## Why

Rockchip RT-Thread SDK 从 3.1.3 升级到 4.1.1 后，BSP 默认配置、驱动控制 API、
目录中的子模块占位和 RK3568 外设默认值均发生变化，直接替换 vendor 树会导致构建失败、
AMP 单核配置失效以及 UART7 启动日志丢失。需要把本次上板恢复出的约束固化到构建基线、
运行期规范和升级文档中，使后续 SDK 同步可重复验证。

## What Changes

- 同步 Rockchip RT-Thread 4.1.1 SDK，并保留 RK3568 AMP 所需的 UART7、GIC IRQ、
  rpmsg-lite platform 和串口生命周期兼容改动。
- 引入 flange 管理的 RT-Thread AMP 基线配置，按 BSP、平台基线、app 差异的顺序合并，
  统一关闭 SMP 并启用 Linux rpmsg 协同选项。
- 调整 RT-Thread staging，使构建只复制可写的 Rockchip BSP，显式复用 flange HAL SDK，
  并容忍 vendor 树中的断链子模块占位。
- 约束 Orange Pi CM4 的 RT-Thread app 关闭 GMAC1 和 UART2，防止 BSP 默认 pinmux
  覆盖 UART7_M2 或接管 Linux console。
- 增加配置回归测试、启动与 RPMsg 上板验收项，并记录 SDK 升级排障方法。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `amp-firmware-build`：补充 RT-Thread 4.1.1 staging、平台基线配置及缓存失效要求。
- `amp-runtime-bringup`：补充单核 AMP、串口启动可观测性和 UART pinmux 独占要求。
- `rockchip-orangepi-cm4`：补充 UART7 app 必须关闭 GMAC1/UART2 默认项的板级约束。

## Impact

- vendor 源码：`components/amp/rockchip/rt-thread/`
- 构建逻辑：`builder/platforms/rockchip/amp.py`
- 平台数据：`components/platform/rockchip/amp/rt-thread.config`
- app 配置：`components/app/rk3568_amp_uart7_rtt_demo/.config`
- 文档与测试：`docs/`、`components/board/orangepi-cm4/docs/`、`tests/builder/`

## 非目标

- 不把 RK3568 AMP 改为 SMP，也不让 RT-Thread 管理 Linux 使用的 cpu0/cpu1/cpu2。
- 不修改 Linux stock rpmsg 驱动，不改变 link-id、endpoint 名称或共享内存布局。
- 不在本次升级中重构 RT-Thread vendor SDK 的无关模块。
