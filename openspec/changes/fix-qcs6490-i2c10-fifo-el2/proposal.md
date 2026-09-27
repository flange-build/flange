## Why

`radxa-dragon-q6a-*` 在 EL2（KVM）下无法启动。UEFI（SPI 固件 `260120`/00549-KODIAKWP）的 `Hypervisor Override` 开启后，Radxa UEFI 在 ExitBootServices 前给 GRUB 加载的 DTB 打上 KVM fixup（`/chosen` 出现 `radxa,enable-kvm`、`radxa,dtb-fixup-applied`），Linux 以 EL2 启动。udev 加载 `i2c_qcom_geni` 时，`i2c10`（RTC `st,m41t11`，`i2c@a88000`，DT 声明 `qcom,enable-gsi-dma`）走 GPI DMA 申请通道，`gpi_config_interrupts()` 读 gpii 1 的 `GPII_n_CNTXT_MSI_BASE_LSB`（`0x23188 + 0x4000*1`）时触发同步外部中止（`ESR 0x96000010`），内核 Oops 后整机复位；另一次复现为异步 `SError` 直接 panic。同一 4K 页内前序寄存器（`0x23088`～`0x23120`）读写均成功，说明是寄存器级访问控制，而非时钟或整页映射问题。

实板已证实：GRUB 追加 `module_blacklist=i2c_qcom_geni` 后系统在 EL2 下正常启动到 rootfs（`CPU: All CPU(s) started at EL2`、`/dev/kvm` 存在），GPI 是唯一阻断点。用户需要 Q6A 在 EL2 下工作（硬件编码仅 EL2 可用）。

## What Changes

- 新增 kernel patch `components/platform/qualcommqcs6490/patches/kernel/0007-dts-radxa-dragon-q6a-i2c10-drop-gsi-dma.patch`：从 `qcs6490-radxa-dragon-q6a.dts` 的 `&i2c10` 删除 `qcom,enable-gsi-dma`。
- 复用既有 `0006`：DT 未声明 `qcom,enable-gsi-dma` 而 SE 被 bootloader 预 provision 成 GSI 时，probe 重 provision 回 FIFO。`0006` 代码不变，仅更新其 patch 说明中"仅命中 i2c13"的表述。
- 结果：Q6A 所有启用的 i2c 总线（`i2c10`、`i2c13`）均走 FIFO，不再申请 GPI DMA 通道；EL1 与 EL2 均可启动，不依赖 UEFI `Hypervisor Override` 设置。
- **BREAKING（规格层面）**：推翻 `fix-qcs6490-touch-i2c13-fifo` 规格中"`i2c10` 保持 GSI、SHALL NOT 受影响"的约束。
- 更新 `wiki/boards/radxa-dragon-q6a.md`：记录 EL2 下 GPI 中止根因、UEFI 自行套用 KVM fixup 的机制、i2c10 改 FIFO。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `qcs6490-mainline-kernel`：
  - 新增要求：Q6A 启用的 i2c 总线 SHALL NOT 使用 GPI DMA，保证 EL1/EL2 均可启动。
  - "魅族 E3 屏在 mainline 重验通过"要求：删除"SHALL NOT 影响 `i2c10`（GSI 正常）"约束及对应场景，重 provision 触发面由"仅 i2c13"扩展为"所有 DT 未声明 GSI 的 i2c SE"。
  - "内核基线切换到 mainline linux-7.0.2"要求的 patch 应用场景：`0001–0006` → `0001–0007`，且 `i2c10` 不含 `qcom,enable-gsi-dma`。

## Impact

- **代码**：新增 `patches/kernel/0007-*.patch`；`0006` 仅改说明文字。patch 由 `sorted(glob("*.patch"))` 自动纳入，无需登记。
- **产物**：`radxa-dragon-q6a-{default,desktop,meizu-e3-bringup}-*` 的 DTB 变化，kernel 组件及下游重建。
- **运行时**：RTC（m41t11，少量字节事务）由 GSI 改为 FIFO，功能无差异；GPI 控制器 `gpi_dma1` 仍 probe，但无客户端。
- **验证**：`flange build` + `flange flash` 后实板在 EL2 下不加 `module_blacklist` 启动，RTC 可读写。
- **文档**：`wiki/boards/radxa-dragon-q6a.md`。

## 非目标

- 不让 flange 默认产物自带 EL2（不在 DTB `/chosen` 写 `radxa,enable-kvm`、不新增 el2 dtso）；EL1/EL2 仍由 UEFI `Hypervisor Override` 决定，Radxa UEFI 在开启时自行套用 KVM fixup。
- 不修 GPI 驱动（不跳过 MSI 寄存器访问），不深究固件为何在 EL2 下封锁 GPII MSI 寄存器。
- 不改 SPI 固件与 UFS 布局。
- 不处理 EL2 下 ADSP/CDSP、音频等其它子系统的状态，仅保证启动与 i2c 可用。
