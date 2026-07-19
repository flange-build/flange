## ADDED Requirements

### Requirement: ATK-RK3506B 提供独立 Fluxion product

板级配置 SHALL 同时提供 default 与 fluxion product。default MUST 继续选择已验证的
UART4/RPMsg echo AMP App；fluxion SHALL 选择 Fluxion FOC AMP App并安装 Linux bridge，
不得改变既有内存、分区、mailbox 和 endpoint 事实源。

#### Scenario: default 救援构建

- **WHEN** 用户 lunch `atk-rk3506b-default-debug`
- **THEN** 不解析 Fluxion OOT App，AMP 固件仍为 rk3506_amp_uart4_rtt_demo

#### Scenario: Fluxion 完整构建

- **WHEN** 用户 lunch `atk-rk3506b-fluxion-debug`
- **THEN** amp 选择 rk3506_amp_fluxion_foc，rootfs 安装 fluxion-rpmsg-bridge
