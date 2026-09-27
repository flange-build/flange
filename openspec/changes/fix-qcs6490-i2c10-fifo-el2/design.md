## Context

实板取证（2026-09-27，SPI 固件 `260120`/00549-KODIAKWP，UEFI `Hypervisor Override` 开启）：

- UEFI 在 ExitBootServices 前对 GRUB 经 `devicetree` 加载的 flange DTB 打 KVM fixup。活动 DT（`/sys/firmware/fdt`）与 flange DTB 的差异正是 radxa `qcs6490-radxa-dragon-q6a-kvm.dtso` 的内容加 Radxa 平台 fixup：`/chosen` 的 `radxa,enable-kvm`/`radxa,dtb-fixup-applied`、scm `qcom,shm-bridge-vmid`、venus 追加 iommus 与 `video-firmware`、PCIe ranges/iommu-map、adsp/cdsp `qcom,broken-reset` 等。GPI 与 i2c 节点未被改动。
- Linux 以 EL2 启动（VHE），`/dev/kvm` 存在。
- 崩溃调用链：`geni_i2c_probe` → `dma_request_chan` → `gpi_of_dma_xlate` → `gpi_alloc_chan_resources` → `gpi_config_interrupts`。故障指令 `ldr w3, [x1]`，`x1 = ee_base + 0x4000 + 0x23188`，即 gpii 1 的 `GPII_n_CNTXT_MSI_BASE_LSB`。`gpi_update_reg()` 先读后写，前序 `TYPE_IRQ_MSK`(0x23088)…`GPII_IRQ_EN`(0x23120) 的读都成功，到 MSI 寄存器才中止。
- 启用的 i2c 里只有 `i2c10`（`i2c@a88000`，gsi flag 在）与 `i2c13`（`i2c@a94000`，`0003` 已删 flag、`0006` 重 provision 回 FIFO）引用 `gpi_dma1`。`i2c13` 不申请 DMA，申请者只有 `i2c10`。
- `module_blacklist=i2c_qcom_geni` 时 EL2 下完整启动，可见 GPI 是唯一阻断点。
- 历史对照：6.18.2（固件 `251013`，EL1）与 6 月 `0006` 验证时 GPI 通道分配都成功过，后者的 EL 状态未记录。`260120` + EL2 是首次确认的失败组合。

`0006` 的触发条件是通用的："DT 未声明 `qcom,enable-gsi-dma` 且 SE 起来是 GSI"，并不绑定 SE5。

## Goals / Non-Goals

**Goals:**

- Q6A 在 EL2 下不加任何启动参数即可启动到 rootfs。
- Q6A 不再依赖 GPI DMA，EL1/EL2 行为一致，不受 UEFI `Hypervisor Override` 设置影响。
- 改动最小：只删一个 DT 属性，复用已验证的 `0006`。

**Non-Goals:**

- 不修 GPI 驱动，不查明 EL2 下 GPII MSI 寄存器被封锁的固件侧原因。
- 不让 flange 产物主动选择 EL2（不写 `radxa,enable-kvm`）。
- 不处理 EL2 下其它子系统。

## Decisions

### 决策 1：删 `i2c10` 的 `qcom,enable-gsi-dma`，交由 `0006` 重 provision 回 FIFO（选定）

新增 `0007` DTS patch，与 `0003`（i2c13）同形。`0006` 在 probe 时见 DT 无 flag 而 SE 为 GSI，就重调 `geni_load_se_firmware(GENI_SE_I2C)`，flag 缺席时按 FIFO provision；若 bootloader 未 provision（`proto==INVALID`），原有分支同样按 FIFO 加载。之后 `fifo_disable` 为假，不调用 `dma_request_chan`，GPI 寄存器不会被访问。

理由：RTC 每次只传几个字节，FIFO 完全够用；`0006` 已在 i2c13 实板验证安全（probe 早期、无在途传输）。这一改动与 EL 状态无关，也不依赖固件行为。

保留 `dmas`/`dma-names`：只有 `fifo_disable` 为真时才会使用，删掉反而扩大 diff。

### 备选 A：patch `gpi.c` 跳过 MSI 寄存器读写（否决）

写入值本来就是 0（关闭 MSI），跳过看似无害。但 MSI 之后还有 `SCRATCH_0/1`、`INTSET`、`ERROR_LOG`、通道/事件环上下文等寄存器，无法确认哪些同样被封锁（首次复现是异步 SError，定位不精确）；而且改的是通用 DMA 驱动，影响面大，最终仍要实板逐个试。

### 备选 B：禁用 `gpi_dma1`（否决）

`i2c10` 仍是 GSI 时，`dma_request_chan` 拿不到通道会让 probe 失败或无限 defer，RTC 不可用。

### 备选 C：要求 EL1（否决）

用户需要 EL2（硬件编码）；而且这样会把启动能力绑在 UEFI 设置上，一旦被改就起不来。

### 决策 2：更新 `0006` 的说明文字，不改代码

`0006` 的说明与代码注释写的是"仅命中 i2c13"。代码本来就是通用条件，只需把说明改为"命中所有 DT 未声明 GSI 的 i2c SE（i2c10/i2c13）"。因为 patch 内容哈希变化会触发 kernel 重建，与 `0007` 一起重建即可，不额外增加成本。代码注释里写的是 SE5，也一并改成通用描述。

## Risks / Trade-offs

- [`0006` 在 i2c10 上重 provision 的安全性] → 与 i2c13 同一路径，probe 早期执行、无在途传输。缓解：实板读写 RTC（`hwclock -r` / `hwclock -w`）验证。
- [FIFO 模式 RTC 行为] → m41t11 为小事务低速设备，FIFO 是 geni i2c 的默认模式。缓解：实板验证读写。
- [meizu-e3-bringup 回归] → 只改 i2c10，i2c13 路径不变。缓解：该 product 构建通过；实板屏幕回归不属于本次必做范围，记为可选验证。
- [未来新增 i2c/spi 节点再带 gsi flag] → 规格新增"启用的 i2c 不使用 GPI"要求，作为评审约束。

## Migration Plan

1. 新增 `0007`，更新 `0006` 说明 → `flange build` → `flange flash`（只刷 UFS，SPI 保持 `260120`）。
2. 回滚：删除 `0007` 重建即可恢复 GSI（仅 EL1 可用）。
