## Why

ATK-RK3506B 的两路 YT8512C PHY 虽能被 MDIO 识别，但当前 kernel 分支中的
Motorcomm 初始化流程与可正常工作的 ATK BSP 不一致，导致网线插拔后 carrier 仍不能稳定建立。
实机复位曾短暂触发 Link Up，且 DTS、时钟与 Kconfig 已排除差异，因此需要把目标 PHY 的初始化
顺序收敛到 BSP 已验证流程。

## What Changes

- 通过 ATK-RK3506B 板级 kernel patch 对齐 YT8512C（PHY ID `0x00000128`）的 BSP 初始化流程。
- 修复 LED1 配置被写入错误扩展寄存器的问题。
- 移除当前分支额外的 RMII PLL/combo 寄存器改写，在关闭 auto-sleep 后执行最终 software reset。
- 对齐目标 PHY 的 Linux 6.1 driver callbacks，并增加静态回归、patch 可应用性和 kernel 构建验证。
- 记录刷写后冷启动及两路网口插拔验收要求。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `rockchip-atk-rk3506b`: 增加 YT8512C 初始化必须与 ATK BSP 已验证顺序一致并能稳定建立 carrier 的要求。

## Impact

- 代码：`components/board/atk-rk3506b/patches/kernel/`。
- 测试：ATK-RK3506B 板级配置与 kernel patch 静态回归测试。
- 构建：目标板 kernel 内容哈希变化，将触发 kernel/boot 相关增量重建。
- 硬件：只影响 ATK-RK3506B 的两路 YT8512C RMII PHY，不改变 GMAC DTS、时钟方向或其他 board。

## 非目标

- 不整体替换当前 kernel 的 Motorcomm driver，也不改变其他 Motorcomm PHY 型号的行为。
- 不修改已与 BSP 一致的 GMAC/MDIO DTS、clock/reset/pinctrl 或 Ethernet Kconfig。
- 不在本变更中调整 U-Boot、PHY 硬件 strap、原理图或 rootfs 网络管理策略。
