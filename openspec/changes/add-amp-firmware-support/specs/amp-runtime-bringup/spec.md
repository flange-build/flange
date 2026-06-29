## ADDED Requirements

### Requirement: U-Boot 启用 AMP loader 从 amp 分区拉起从核

flange SHALL 为 Rockchip bootloader 提供启用 AMP 的配置（经 `bootloader.defconfig` 的 **raw inline option** 机制——board 层用 `+defconfig:<product>` 追加 `CONFIG_AMP=y` / `CONFIG_ROCKCHIP_AMP=y`，bootloader builder 把含 `=` 的项 append 进 `.config` 后 `make olddefconfig` 归一化；配置增加走配置、不走 patch），同时启用 `CONFIG_AMP=y` 与 `CONFIG_ROCKCHIP_AMP=y`（其依赖 `ROCKCHIP_SMCCC`、`RKIMG_BOOTLOADER` 在目标 SoC 上已满足，`olddefconfig` 据 Kconfig 依赖保留之）。`bootloader.defconfig` SHALL 支持单字符串或 list 两形态（list 中含 `=`/`# CONFIG_` 的项为 raw option、其余为 defconfig/fragment make 目标），使该机制与 `kernel.defconfig` 一致。启用后 U-Boot SHALL 按分区名 `amp` 读取 FIT、把各核固件搬到其 `load` 地址、用 SMC/PSCI 拉起从核，并（amp_linux.its 路线）继续引导 Linux 到主核。两个 config SHALL 成对启用（仅开 `CONFIG_AMP` 会因 `arm64_switch_amp_pe`/`amp_cpus_on` 无定义而链接失败）。

#### Scenario: u-boot 配置含成对 AMP 选项

- **WHEN** 构建出目标板 u-boot 并查看其 `.config`
- **THEN** 同时含 `CONFIG_AMP=y` 与 `CONFIG_ROCKCHIP_AMP=y`

#### Scenario: 无 amp 分区时正常启动不受影响

- **WHEN** 启用 `CONFIG_AMP` 但设备无 amp 分区（或 amp 分区为空）
- **THEN** `amp_cpus_on()` 因 `part_get_info_by_name("amp")` 失败而早退（`-ENODEV`），主系统照常启动 Linux

### Requirement: 目标板 Linux DTS 接入 AMP 通信节点

flange SHALL 为目标板提供一个**专用 AMP dts 文件**（经 board kernel patch 新增到内核树，由 amp product 的 `kernel.dts` 选用），内容为基础板 dts 加三类 AMP 改动：(a) `#include "rk3568-amp.dtsi"`（或等价内联）接入 `reserved-memory`（amp_shmem / rpmsg / rpmsg_dma / mcu 段）、`rockchip-amp`（amp-cpus entry + amp-irqs）、`rpmsg`（`rockchip,rpmsg` + `mboxes` + `memory-region`）并使能 `&mailbox`（status = okay）；(b) `/delete-node/ &<amp-core>;` 把分给 AMP 的 cpu 节点（tspi-rk3566 为 cpu3）从 Linux 摘掉，使 Linux 不去 online 该核；(c) 确保 AMP 从核 console 所用 UART（默认 UART4）不被 Linux 占用。reserved-memory 与 amp-cpus entry 地址 SHALL 与 amp 固件内存布局（SHMEM_BASE / LINUX_RPMSG_BASE / 从核 load 地址）一致。改动 SHALL 走独立 dts 文件 + product 选用，SHALL NOT 写成会改基础板主 dts 的 board patch（patch 按板对所有 product 生效，会污染非 amp product）；也 SHALL NOT 走运行时 overlay（目标板 extlinux 默认不应用 overlay）。因 DTS 走静态 patch、无法在构建期消费 SoC 内存布局常量（与 build.sh/.its 两腿由构建器注入不同），flange SHALL 提供一个构建期/校验期交叉比对：把 patch 内的 reserved-memory / amp-cpus entry 地址与 SoC 内存布局常量逐项比对，不一致 SHALL 使构建/校验失败——以此把 DTS 这条手工腿纳入内存布局单一事实源的一致性保障，避免「改了常量忘改 patch」无人拦截。

#### Scenario: 编出的 dtb 含 AMP 节点

- **WHEN** 用 amp product（如 `tspi-rk3566-amp`）构建内核并反编译其 dtb
- **THEN** 含 `compatible = "rockchip,rpmsg"` 节点、四段 AMP `reserved-memory`、`rockchip-amp` 节点
- **AND** `mailbox` 节点 `status` 为 `okay`

#### Scenario: AMP 从核的 cpu 节点被摘出 Linux

- **WHEN** 用 amp product 构建并反编译 dtb，或上板执行 `nproc`/`cat /proc/cpuinfo`
- **THEN** dtb 中分给 AMP 的 cpu 节点（tspi-rk3566 为 `cpu@300`/cpu3）不存在
- **AND** Linux 仅枚举 3 个 CPU（cpu0/1/2）

#### Scenario: default product 不受 AMP dts 影响

- **WHEN** 用 `default` product（非 amp）构建内核
- **THEN** 其 dtb 不含 AMP 节点、cpu 节点齐全（4 核），不选用 amp dts 文件

#### Scenario: DTS 地址与 amp 固件一致

- **WHEN** 比较 DTS 的 reserved-memory/amp-cpus entry 地址与 amp 固件注入的 SHMEM/LINUX_RPMSG/load 地址
- **THEN** 对应段地址逐字节一致（同一内存布局事实源）

#### Scenario: DTS 地址与 SoC 常量不一致时被拦截

- **WHEN** board kernel patch 内的 reserved-memory/amp-cpus 地址与 SoC 内存布局常量不一致
- **THEN** 构建期/校验期交叉比对失败，给出明确错误（指出哪段地址不匹配）

### Requirement: 内核暴露 rpmsg 字符设备供用户态通信

需要 amp 通信的 SoC 内核配置 SHALL 追加 `CONFIG_RPMSG_CHAR=y` 与 `CONFIG_RPMSG_CTRL=y`（经 `kernel.defconfig` 的 raw inline 机制注入）。理由：现有 defconfig 虽已开 `RPMSG_ROCKCHIP_MBOX`/`RPMSG_VIRTIO`，但没有任何选项会 select 这两项，缺它们则无 `/dev/rpmsg_ctrlN`、`/dev/rpmsgN`，用户态 app 无法直接收发。

#### Scenario: 内核 .config 含 rpmsg 字符设备

- **WHEN** 构建目标板内核并查看 `.config`
- **THEN** 含 `CONFIG_RPMSG_CHAR=y` 与 `CONFIG_RPMSG_CTRL=y`

#### Scenario: 运行时暴露 rpmsg 字符设备（上板验证）

- **WHEN** amp 固件运行、Linux 起来后在目标设备上查看 `/dev`
- **THEN** 存在 `/dev/rpmsg_ctrlN`，且用户态经 `RPMSG_CREATE_EPT_IOCTL` 创建端点后出现 `/dev/rpmsgN`

### Requirement: AMP↔Linux rpmsg 链路建立与双向收发

flange 交付的 amp product（dts + amp app 固件 + 内核）SHALL 共同满足 rpmsg-lite 从核与 Linux master 之间「链路握手 + name-service 通告 + 双向数据」的三项约束，缺一则链路不通（上板表现为从核卡 `rpmsg_lite_wait_for_link_up`，或 link-up 成功但 Linux 无对应 rpmsg 通道）：

**(a) rpmsg 邮箱中断路由到从核（DTS amp-irqs）。** 从核 `rpmsg_lite_wait_for_link_up` 死等本核 RAM 的 `link_state`，它仅在从核收到 Linux 发来的首条 mailbox 中断——MBOX0 通道3 A2B 方向，INTID 222 / GIC SPI 190——经 ISR 置 1（与共享内存/cache 无关）。该 IRQ SHALL 列入 `rockchip-amp` 的 `amp-irqs` 并路由到 AMP 核（tspi-rk3566 = cpu3）。否则 Linux `gic_dist_init`（irq-gic-v3）会把未列入 amp-irqs 的 SPI 的 GICD_IROUTER 强制改回 boot CPU(cpu0)、盖掉从核自设的 222→AMP 核路由，使从核永久阻塞在 wait_for_link_up。

**(b) 从核不接管 GIC 分发器（amp app 固件）。** amp app 固件的 `GIC_IRQ_AMP_CTRL.cpuAff`/`defRouteAff` SHALL 设为**非本核**（Linux master 所在 cpu0），使 `HAL_GIC_Init` 判定 `gicInit=0`——从核仅等待 Linux 配置好 AMP 路由后使能自身 IRQ，SHALL NOT 重初始化 GIC 分发器。设为本核会令 `gicInit=1`、从核与 Linux 抢 GICD 致挂死（即「把 222 加进 amp-irqs 却停止打印」的真因）。

**(c) 反向通道唤醒接收 vring（内核 rockchip_rpmsg_mbox patch）。** rpmsg-lite `platform_notify` 对所有 vq 恒用同一 mailbox 通道（= remote cpu id），即从核的新消息（name-service 通告/数据）与 consume 通知都发往同一通道（DT `rpmsg-tx`），而非 rx/tx 各走一条。Linux `rockchip_rpmsg_mbox` 该通道的回调 SHALL 同时唤醒接收 vring（`vring_interrupt(vq[0])`），否则从核的 NS 通告不被 virtio 处理、Linux 无对应 rpmsg 通道与 `/dev/rpmsgN`。（rockchip mailbox 每 channel 双向、mbox 框架不允许同 channel 双绑，故无纯 DTS 改法。）

#### Scenario: 从核 link-up 成功

- **WHEN** amp 固件运行、Linux 起来后查看从核 console（UART4）
- **THEN** 打印 `rpmsg: link up` 与端点 `announced`（说明 `wait_for_link_up` 已返回、收到了 INTID 222 邮箱中断）

#### Scenario: Linux 建出从核通告的 rpmsg 通道

- **WHEN** 从核 `rpmsg_ns_announce` 后在 Linux 查看 `/sys/bus/rpmsg/devices`
- **THEN** 出现从核通告的通道（如 `rpmsg-ap3-ch0`，地址与固件端点一致），dmesg 含 `creating channel`

#### Scenario: 端到端双向收发

- **WHEN** 经 `/dev/rpmsg_ctrl0` 创建匹配该通道的端点得 `/dev/rpmsgN`，向其写入数据
- **THEN** 读回从核 echo（双向数据路径通：Linux→从核走 A2B 通道、从核→Linux 走 B2A 通道并唤醒 vq[0]）
