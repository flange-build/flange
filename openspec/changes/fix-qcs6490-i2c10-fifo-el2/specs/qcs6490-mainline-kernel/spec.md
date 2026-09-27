## ADDED Requirements

### Requirement: Q6A 启用的 i2c 总线不使用 GPI DMA

`radxa-dragon-q6a-*` 产物中所有 `status = "okay"` 的 geni i2c 总线（当前为 `i2c10` RTC、`i2c13` 外接触摸）SHALL 运行于 FIFO 模式，SHALL NOT 申请 GPI DMA 通道。系统 SHALL 在 UEFI `Hypervisor Override` 关闭（EL1，Gunyah）与开启（EL2，KVM，Radxa UEFI 自行套用 KVM fixup）两种状态下都能启动到 rootfs。

> 根因（实板，SPI 固件 `260120`/00549-KODIAKWP，EL2）：`i2c10` 走 GSI 时，`gpi_config_interrupts()` 读 gpii 1 的 `GPII_n_CNTXT_MSI_BASE_LSB` 触发同步外部中止（`ESR 0x96000010`；另一次复现为异步 `SError` panic），udev 加载 `i2c_qcom_geni` 即崩溃复位。同页前序寄存器可访问，属于寄存器级访问控制。由 `patches/kernel/0007` 删除 `i2c10` 的 `qcom,enable-gsi-dma`，再由 `0006` 把 bootloader 预 provision 的 GSI 重 provision 回 FIFO。

#### Scenario: EL2 下不加启动参数即可启动
- **WHEN** UEFI `Hypervisor Override` 开启、刷入本修复后的镜像并上电，GRUB 使用默认启动参数（不含 `module_blacklist`）
- **THEN** 内核打印 `CPU: All CPU(s) started at EL2`、`/dev/kvm` 存在，`i2c_qcom_geni` 加载无 Oops/SError，系统启动到 rootfs 且 adb/串口可登录

#### Scenario: i2c10 走 FIFO 且 RTC 可用
- **WHEN** 系统启动后 `i2c10`（`i2c@a88000`）probe
- **THEN** 活动 DT 中 `i2c@a88000` 不含 `qcom,enable-gsi-dma`，`dmesg` 无 `gpi` 通道分配与 `GPI transfer failed`，RTC `m41t11` 注册为 `/dev/rtc*`，且 `hwclock -r` 读、`hwclock -w` 写均成功

#### Scenario: EL1 下行为不回归
- **WHEN** UEFI `Hypervisor Override` 关闭（EL1）启动同一镜像
- **THEN** 系统同样启动到 rootfs，`i2c10` 走 FIFO、RTC 可读

## MODIFIED Requirements

### Requirement: 魅族 E3 屏（meizu-e3-bringup product）在 mainline 重验通过

`radxa-dragon-q6a-meizu-e3-bringup-*` 产物 SHALL 在 mainline 6.18.2 基线上完成魅族 E3 39pin MIPI-DSI 屏的显示 + 触摸 + 背光 bring-up：经 `meizu-e3-panel` 包注入的 `panel_meizu_e3`/`sec_ts`/`sgm37604a` 三个 OOT 驱动 SHALL 能对 mainline 6.18 内核编译通过（适配 `asm/fb.h`/`asm/unaligned.h` 移除、`GPIOF_DIR_IN`→`GPIOF_IN`、`FB_EVENT_BLANK` 移除等 ABI 漂移，并 SHALL 同时保持 rock5b/a7a 旧 BSP 内核可编）。

触摸/背光所在 `i2c13`（QUP1 SE5 `@a94000`）SHALL 实际运行于 geni i2c 的 FIFO 模式以避免 GPI DMA 传输失败。在 linux-7.0.2 上**仅**从 base board dts 去除 `qcom,enable-gsi-dma`（`patches/kernel/0003`）**不充分**——bootloader（对齐 radxa rsdk）已将该 SE 预 provision 成 GSI（`proto==GENI_SE_I2C`、`FIFO_IF_DISABLE` 置位），而 `i2c-qcom-geni` probe 在 `proto` 已初始化时跳过 `geni_load_se_firmware()`，`qcom,enable-gsi-dma` 永不被读。故内核 SHALL 由 `patches/kernel/0006` 在"DT 未声明 `qcom,enable-gsi-dma` 且 SE 起来为 GSI（`GENI_IF_DISABLE_RO & FIFO_IF_DISABLE` 置位）"时强制重调 `geni_load_se_firmware(GENI_SE_I2C)` 把该 SE 重 provision 回 FIFO；`patches/kernel/0003` 仍保留（删 flag 是该触发条件之一）。该重 provision SHALL 命中所有满足失配条件的 i2c SE（`i2c13`，以及经 `patches/kernel/0007` 删除 flag 的 `i2c10`），SHALL NOT 影响 DT 仍声明 `qcom,enable-gsi-dma` 的 SE 与 `default` 产物的其余行为。

#### Scenario: 显示 + 触摸 + 背光实板可用
- **WHEN** 刷入 meizu-e3-bringup 产物并上电、屏接到 J10 LCD FPC
- **THEN** `/sys/class/drm/card0-DSI-1` 为 `connected`/`enabled` @ 1080×2160 且面板有画面、`sec_ts` 读到 device id `AC,6F,70` 且手指触摸使其 IRQ(gpio81) 计数累增、`/sys/class/backlight/sgm37604a` 亮度可写且生效

#### Scenario: i2c13 走 FIFO、无 GPI DMA 传输失败
- **WHEN** meizu-e3-bringup 产物开机、`sec_ts`/`sgm37604a` 在 `i2c13` 上 probe
- **THEN** `dmesg` 无 `geni_i2c ... GPI transfer failed` / `prep_slave_sg failed` / `gpi ... Error in Transaction`，`sec_ts` 读到 device id `AC,6F,70`，触摸（`evtest /dev/input/event1` 出坐标事件）与背光的 i2c 读写均成功

#### Scenario: bootloader 预 provision GSI 时内核重 provision 回 FIFO
- **WHEN** 某 i2c SE（`i2c13`/SE5 或 `i2c10`）被 bootloader 预 provision 成 GSI（`FIFO_IF_DISABLE` 置位、`proto==GENI_SE_I2C`）且 dts 未声明 `qcom,enable-gsi-dma`
- **THEN** 内核 `i2c-qcom-geni` probe SHALL 重调 `geni_load_se_firmware(GENI_SE_I2C)` 清除 `FIFO_IF_DISABLE`，使该 SE 以 FIFO 模式工作（`gpi_mode=false`、不再走 GPI）

### Requirement: 内核基线切换到 mainline linux-7.0.2

系统 SHALL 将 qcs6490 SoC 的内核源分支配置为 `radxa/kernel.git` 的 `linux-7.0.2`（mainline 7.0 系，Radxa linux-qcom 官方包同款分支），并 SHALL 复用现有 `grub-with-dtb` 的 boot/image/EDL 刷写流水线；构建出的内核 Image 与 dtb SHALL 来自该分支。

内核源 SHALL 在 `branch=linux-7.0.2` 基础上 pin `commit=7473a9fca2b08623319e497f4f811746baddb7bc`（= radxa linux-qcom 7.0.2-2 的 `src` 子模块），不跟随分支 tip（tip 已前移到会触发 UFS 复位的 commit）。

内核 config SHALL 对齐 radxa rsdk/linux-qcom 的**四段叠加**配方：`make defconfig qcom_module.config radxa.config radxa_custom.config`（顺序固定，后者覆盖前者）。其中 `qcom_module.config` 为内核 in-tree，`radxa.config` / `radxa_custom.config` 由 patch 注入。flange 特定符号 MUST 统一通过 `kernel.config` 在四段后渲染，包含 `FW_LOADER_COMPRESS*`、USB gadget 相关符号以及 `CONFIG_MODULE_SIG_FORCE: "n"`。

#### Scenario: 内核从 linux-7.0.2 构建成功
- **WHEN** 配置 `sources.linux-qcs6490.branch = linux-7.0.2` + `commit = 7473a9f` 并执行 `flange build kernel`
- **THEN** 成功检出该 commit 并编出 `Image` 与 `qcs6490-radxa-dragon-q6a` 对应的 dtb，无构建中断

#### Scenario: 四段 config 片段被正确合并
- **WHEN** 内核构建完成
- **THEN** 最终 `.config` 中 `qcom_module.config` 的 qcom 平台驱动均为 `=y`（如 `CONFIG_QCOM_AOSS_QMP`、`CONFIG_QCOM_LLCC`、`CONFIG_QCOM_QSEECOM`、`CONFIG_SCSI_UFS_QCOM`、`CONFIG_ARM_SMMU_V3`），radxa.config 典型项（`CONFIG_DMABUF_HEAPS=y` 等）与 radxa_custom.config 项（`CONFIG_MODULE_COMPRESS_ZSTD=y`、`CONFIG_EFI_ZBOOT` 未设）齐备

#### Scenario: kodiak.dtsi 基础上 patch 正确应用
- **WHEN** 内核构建时按序应用 0001–0007 patch（含同 commit 重建：`reset_source` 先 `git clean -fd` 清未跟踪残留）
- **THEN** `qcs6490-radxa-dragon-q6a.dts` 中 `usb_1` 的 `dr_mode` 为 `peripheral`、`i2c10` 与 `i2c13` 均不含 `qcom,enable-gsi-dma`，`drivers/i2c/busses/i2c-qcom-geni.c` 含 `0006` 的"GSI/FIFO 失配则重 provision 回 FIFO"分支，`radxa.config`/`radxa_custom.config` 被创建，全部 patch 无 `already exists` / 冲突报错
