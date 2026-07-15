# rk3506b-amp-rtt-demo Specification

## Purpose
TBD - created by archiving change add-rk3506b-atk-rk3506b. Update Purpose after archive.
## Requirements
### Requirement: RK3506B RT-Thread demo 在 CPU2 单核运行

项目 SHALL 提供 `rk3506_amp_uart4_rtt_demo` AMP app，并以 `mode=rt-thread` overlay 到
`rk3506-32` BSP。固件 SHALL 在 MPIDR `0xf02` 的 CPU2 单核运行，MUST NOT 启用 RT-Thread
SMP 或拉起 Linux 所属 CPU0/CPU1。

#### Scenario: 固件配置为 CPU2 单核
- **WHEN** 构建 RK3506B AMP app
- **THEN** 最终配置未启用 `RT_USING_SMP`
- **AND** AMP FIT 的 `amp2.cpu` 为 `0xf02`

### Requirement: AMP 固件内存布局与 RK3506 DTS 一致

AMP 配置 SHALL 使用 CPU2 firmware `0x03e00000/0x00100000`、shared memory
`0x03b00000/0x00100000`、Linux RPMsg `0x03c00000/0x00200000` 和 MCU SRAM
`0xfff80000/0x0000c000`。builder SHALL 在生成 `amp.img` 前交叉校验配置、ITS 与目标 DTS。

#### Scenario: 三方内存布局一致
- **WHEN** 构建 RK3506B `amp.img`
- **THEN** FINAL_CONFIG、渲染后 ITS 与目标 DTS 中对应地址和大小完全一致

#### Scenario: Linux load 地址不被 AMP 渲染器改写
- **WHEN** 渲染同时包含 `images/amp2.load` 与 `configurations/conf/linux.load` 的 ITS
- **THEN** 只更新 `images/amp2` 的 load/size
- **AND** Linux load 保持 `0x00900000`

### Requirement: RT-Thread 通过 UART4 提供启动日志与 MSH

固件 SHALL 使用 UART4 的 `RM_IO27_TX/RM_IO28_RX`，串口参数为 1500000 8N1。RT-Thread
banner、CPU2 启动信息 SHALL 在 RPMsg link-up 前输出，并在启动完成后提供可交互 MSH。

#### Scenario: UART4 启动日志顺序正确
- **WHEN** 冷启动已刷入 AMP 固件的板卡并监听 UART4
- **THEN** 先看到 RT-Thread banner 和 CPU2 启动信息
- **AND** 随后看到 RPMsg link-up/endpoint announce 且 MSH 可交互

### Requirement: RK3506 RPMsg 使用 DTS 定义的 mailbox 与 link-id

固件 SHALL 使用 RK3506 rpmsg-lite port、`link-id=0x02`、CPU2 mailbox IRQ 和
`0x03c00000` 共享区，通告 endpoint address `0x3003`、name `rpmsg-ap3-ch0`。收到 Linux
消息后 SHALL 将 payload echo 回来源 endpoint，不得套用 RK3568 的 `link-id=0x10` 或
INTID 222 workaround。

#### Scenario: Linux 与 RT-Thread link-up
- **WHEN** U-Boot 启动 CPU2 且 Linux RPMsg driver 初始化
- **THEN** UART4 输出 link-up 和 endpoint announced
- **AND** Linux sysfs/dmesg 出现 `rpmsg-ap3-ch0`

#### Scenario: RPMsg 双向 echo
- **WHEN** Linux 通过 `/dev/rpmsg_ctrlN` 创建匹配 endpoint 并向 `/dev/rpmsgN` 写入消息
- **THEN** Linux 从该设备读回内容相同的 echo

### Requirement: AMP 上板验收同时验证 Linux CPU 所有权

硬件验收 SHALL 同时检查 U-Boot 加载 `amp` 分区、RT-Thread 运行、Linux 仅枚举 CPU0/CPU1
以及 RPMsg echo，缺少任一结果不得宣告 AMP bring-up 完成。

#### Scenario: 完整 AMP 验收通过
- **WHEN** ATK-RK3506B 从 SPI NAND 冷启动
- **THEN** U-Boot 日志显示加载 `amp.img`
- **AND** Linux `/proc/cpuinfo` 仅列出两个 Linux CPU
- **AND** UART4 MSH 与 RPMsg echo 均工作
