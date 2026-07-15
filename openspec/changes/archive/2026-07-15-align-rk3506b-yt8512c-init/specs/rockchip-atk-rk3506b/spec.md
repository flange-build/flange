## ADDED Requirements

### Requirement: ATK-RK3506B YT8512C 按 BSP 流程初始化

ATK-RK3506B 的 board kernel patch SHALL 对 PHY ID `0x00000128` 使用 ATK BSP
已验证的 YT8512C 初始化流程。driver SHALL 将 LED0 配置写入扩展寄存器 `0x40c0`、
将 LED1 配置写入扩展寄存器 `0x40c3`，清除扩展寄存器 `0x2027` 的 auto-sleep bit 15，
并在这些配置完成后执行 software reset。初始化 MUST 对每次失败的 MDIO 访问返回错误，
不得把 LED1 配置值误作寄存器地址 `0x0010`。

原理图 strap 已将 PHY 配置为 RMII1 且由 SoC 提供 50 MHz `RMII_REF_CLK`，因此该初始化
SHALL NOT 额外改写扩展寄存器 `0x0050` 或 `0x4000` 来覆盖 strap 模式。目标 PHY driver
条目 SHALL 明确提供会轮询完成的 `genphy_soft_reset` callback；PHY abilities 与
autoneg SHALL 使用 Linux 6.1 PHY core 的默认 fallback。polling SHALL 由 PHY core
在无有效 IRQ 时选择，不得将值为 `-1` 的 `PHY_POLL` 写入 `phy_driver.flags`。

#### Scenario: 板级 patch 静态约束初始化顺序

- **WHEN** 检查 ATK-RK3506B 的 kernel patches
- **THEN** YT8512C LED1 写回地址为 `YT8512_EXTREG_LED1`
- **AND** auto-sleep 写回成功后调用 `genphy_soft_reset`
- **AND** PHY ID `0x00000128` 使用独立 config_init，且不调用 `yt8512_clk_init`
- **AND** PHY ID `0x00000118` 保留现有 `yt8512_clk_init` 流程
- **AND** PHY ID `0x00000128` 的条目包含 `genphy_soft_reset` callback
- **AND** 该条目不硬编码 features 或 config_aneg
- **AND** 该条目不设置 `.flags = PHY_POLL`

#### Scenario: 补丁可构建

- **WHEN** board patch 应用到目标 kernel commit 并在 Docker 中构建 kernel
- **THEN** patch 无冲突且 `motorcomm.o`、目标 DTB 与 `boot.img` 成功生成

#### Scenario: 冷启动后两路网口稳定响应插拔

- **WHEN** 刷入包含该 patch 的 `boot.img` 并断电冷启动
- **THEN** `end0` 与 `end1` 均绑定 ID `0x00000128` 的 Motorcomm PHY driver
- **AND** 任一路接入有效网线后 carrier 变为 1 并产生稳定 Link Up 日志
- **AND** 拔出网线后 carrier 变为 0 并产生 Link Down 日志
- **AND** 连续插拔不依赖手工 `mii-tool -R` 或其他 MDIO reset 命令
