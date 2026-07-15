## Context

ATK-RK3506B 原理图表明两路 PHY 均为 YT8512C，PHYAD 为 1，接口 strap 为
RMII1，`RMII_REF_CLK` 由 SoC 以 50 MHz 输出。实机可读到 PHY ID
`0x00000128`，两路 GMAC、MDIO、reset、pinctrl、clock 与 BSP DTB/Kconfig 均一致；
手工 software reset 曾短暂产生 10 Mbps Full Link Up，问题因此收敛到 PHY 初始化顺序。

当前 kernel 的精简 Motorcomm driver 与 ATK BSP vendor driver 存在三个直接差异：

- 当前 `yt8512_clk_init()` 额外修改扩展寄存器 `0x0050` 与 `0x4000`，而 BSP
  依赖硬件 strap，不执行这组改写。
- 当前 LED1 配置错误写入地址 `0x0010`，BSP 写入 LED1 控制寄存器 `0x40c3`。
- BSP 在关闭 auto-sleep 后执行最终 software reset，并为 ID `0x00000128`
  显式提供 soft reset callback；当前 driver 缺少该无默认 fallback 的 callback。

## Goals / Non-Goals

**Goals:**

- 以 board patch 将 YT8512C 初始化顺序对齐到可工作的 ATK BSP。
- 保留 Linux 6.1 的错误传播和 PHY core 行为，不照搬 vendor driver 的兼容层缺陷。
- 用静态测试锁定寄存器地址、调用顺序、目标 PHY callbacks 和补丁作用范围。
- 通过 patch 可应用性检查与 Docker kernel 构建证明变更可集成。

**Non-Goals:**

- 不整体替换 Motorcomm driver，不修改其他 PHY family 的专用实现。
- 不改变 GMAC DTS、RMII clock direction、reset GPIO 或 Ethernet Kconfig。
- 不把板端刷写及网线插拔结果伪装成主机侧自动测试；硬件验收单独记录。

## Decisions

### 1. 使用 ATK board kernel patch，而不 fork 整个 driver

补丁放在 `components/board/atk-rk3506b/patches/kernel/`，由现有 patch 自动发现机制
纳入该 board 的 kernel 内容哈希。这样既可复现 BSP 差异，又不会把约 3000 行 vendor
兼容代码及其他 PHY 行为带入共享 kernel 源。

备选方案是直接替换 `drivers/net/phy/motorcomm.c`。该方案会同时改变多个未在本板验证的
PHY，回归面过大，因此不采用。

### 2. 初始化依赖硬件 strap，并恢复 BSP 的最终 reset

为 ID `0x00000128` 新增独立 config_init，绕过该型号不需要的 `yt8512_clk_init()`；
ID `0x00000118` 保留当前 clock init。目标型号的配置流程保持为：

1. 配置 LED0 扩展寄存器 `0x40c0`；
2. 配置 LED1 扩展寄存器 `0x40c3`；
3. 清除 auto-sleep 寄存器 `0x2027` 的 bit 15；
4. 通过 `genphy_soft_reset()` 执行 software reset、等待 reset bit 清除，并返回实际错误码。

该顺序与 BSP 的有效流程一致。相比 BSP 中忽略部分返回值且 reset 后不轮询完成的实现，
补丁继续对每次 MDIO 访问做错误检查，并使用 Linux 6.1 的标准 reset helper，避免初始化
失败或 reset 尚未完成就进入下一次 MDIO 访问。

### 3. 只对实机 ID `0x00000128` 显式补齐 soft reset callback

ID `0x00000128` 的条目增加 `.soft_reset = genphy_soft_reset`，使 PHY core 在
config_init 之前先完成一次受轮询保护的 reset；独立 config_init 在写完 LED/auto-sleep 后
再完成一次 reset。LED1 address 修复位于 family 共用 helper，因此也修复旧 ID
`0x00000118` 的明确寄存器地址错误，但其 clock/init 顺序保持不变。

不显式复制 BSP 的 `.features = PHY_BASIC_FEATURES` 与
`.config_aneg = genphy_config_aneg`。Linux 6.1 在字段为空时分别调用
`genphy_read_abilities()` 和 `genphy_config_aneg()`，动态读取实际能力且行为等价。

不复制 BSP 的 `.flags = PHY_POLL`。Linux 6.1 中 `PHY_POLL` 是赋给
`phydev->irq` 的 `-1`，不是合法的 `phy_driver.flags` 位；没有 IRQ callback 时 PHY core
本就自动切换为 polling。照搬会错误置位 `PHY_IS_INTERNAL` 等全部 flag。

### 4. 不改动 `read_status`

carrier 判定已经由当前 `genphy_update_link()` 完成，随后 vendor status 寄存器只覆盖
speed/duplex。BSP 额外调用一次且忽略返回值的 `genphy_read_status()` 不属于初始化流程，
也没有证据表明它能修复本问题，因此本变更不扩大到状态机行为。

## Risks / Trade-offs

- [共用 LED helper 也服务旧 ID `0x00000118`] → 仅修复其确定错误的 LED1 address；
  用独立 config_init 保持该 ID 的 clock/reset 顺序不变。
- [最终 reset 后扩展寄存器可能在未知 silicon revision 上恢复默认] → ATK BSP 对同一
  `0x00000128` 明确采用该顺序，并以实机冷启动/插拔作为最终门禁。
- [主机 kernel build 不能证明物理 carrier] → 产出 boot.img 后必须冷启动分别测试
  `end0`、`end1`，采集 dmesg、carrier 与 PHY 状态。
- [并行工作树已有其他 board 改动] → 仅新增独立 patch、测试与 OpenSpec change，
  不重写或回退现有文件内容。

## Migration Plan

1. 合入 board patch 与静态测试，执行 OpenSpec strict validate。
2. 在 Docker 中强制重建 ATK-RK3506B kernel/boot 产物。
3. 仅刷写新的 `boot.img`，断电冷启动。
4. 分别在 `end0`、`end1` 插拔网线，确认 carrier 和 Link Up/Down 日志稳定变化。
5. 若出现回归，移除该独立 patch 并重建/回刷原 boot.img 即可回滚。

## Open Questions

无。两路 PHY 已在新 `boot.img` 冷启动后完成 Link Up/Down 与切换网口验收，记录见
`evidence/rk3506b-yt8512c-hardware.md`。
