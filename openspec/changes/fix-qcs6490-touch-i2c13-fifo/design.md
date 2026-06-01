## Context

`radxa-dragon-q6a-meizu-e3-bringup`（linux-7.0.2）触摸不响应。实板逐层取证已确诊（详见 proposal「Why」）：

- 链路健康项：`vcc_3v3_lcd`/`tp-reset-deassert` regulator always-on（已上电解复位）；触摸时 `sec_ts` IRQ189(msmgpio 81) 计数 0→158（芯片能检测触摸、拉中断）。
- 失败点：`i2c13`（QUP1 SE5 `@a94000`）在 GSI/GPI-DMA 模式下传输失败——`gpi a00000.dma-controller: Error in Transaction`、运行时 `not enough space in ring`→`geni_i2c a94000.i2c: prep_slave_sg failed`、`GPI transfer failed: -5`；`sec_ts` device id 读成 `0,0,0`（应 `AC,6F,70`）。
- 模式判定机制（7.0.2 内核源码）：
  - `i2c-qcom-geni.c` probe：`proto = geni_se_read_proto()`；仅当 `proto==GENI_SE_INVALID_PROTO` 才调 `geni_load_se_firmware()`（line 1072-1078）。随后 `fifo_disable = readl(GENI_IF_DISABLE_RO) & FIFO_IF_DISABLE` 决定 `gpi_mode`（line 1088-1093）。
  - `qcom-geni-se.c::geni_load_se_firmware()`：`mode` 默认 `GENI_SE_FIFO`，仅当 `of_property_read_bool(se->dev->of_node, "qcom,enable-gsi-dma")` 为真才置 `GENI_GPI_DMA`（line 1330）；`geni_configure_xfer_mode` 据此 清/置 `FIFO_IF_DISABLE`（line 1287-1290）。`qcom,enable-gsi-dma` 的**唯一读取点**就在这里。
- 结论：bootloader（对齐 radxa rsdk）已把 SE5 预 provision 成 I2C-GSI（`proto==I2C`、`FIFO_IF_DISABLE` 置位），probe 跳过固件重载 → `qcom,enable-gsi-dma`（已被 `patch 0003` 从 dts 删除、活动 DT 确认 ABSENT）永不被读 → SE 停留 GSI。**`patch 0003` 在 7.0.2 形同死代码。**
- 对照：`i2c10`（RTC `m41t11`，`@a88000`/SE3，DT **声明** `qcom,enable-gsi-dma`）的 GSI 正常——证明非整个 `gpi_dma1` 坏，而是 SE5 的 GSI provision 坏。FIFO 模式对触摸/背光在 linux-6.18.2 已实板证明可用。

约束：不引入 bootloader/固件侧改动（保持对齐 radxa rsdk）；改动须 `SHALL NOT` 影响 `default` 产物与 `i2c10`；自洽于现有 `0001–0005` kernel patch 集。

## Goals / Non-Goals

**Goals:**

- 让 `i2c13`/SE5 在 7.0.2 实际运行于 FIFO 模式，使 `sec_ts`/`sgm37604a` 的 i2c 读写恢复成功、触摸可用。
- 修复点最小化、可审计，仅在"DT 未要 GSI 但 SE 起来是 GSI"的 mismatch 时触发。
- 更正规格与 wiki 中已被证伪的"删属性即回退 FIFO"结论。

**Non-Goals:**

- 不改 bootloader/XBL/QUP 固件 SE provision 表。
- 不深究 SE5 的 GSI 为何坏（改用已证可用的 FIFO）。
- 不改 `i2c10` 及其它 SE 的 GSI/DMA 行为，不动 `default` 产物。

## Decisions

### 决策 1：在 `i2c-qcom-geni.c` probe 增加"GSI/FIFO 失配则重 provision 回 FIFO"分支（选定）

在 `proto` 判断里追加第三分支：`proto==GENI_SE_I2C`（已初始化）且 DT 未声明 `qcom,enable-gsi-dma` 且 `FIFO_IF_DISABLE` 置位时，强制重调 `geni_load_se_firmware()`。`geni_load_se_firmware` 在 flag 缺席时按默认 `GENI_SE_FIFO` 重 provision → 清 `FIFO_IF_DISABLE` → 之后 `fifo_disable` 读回为假 → `gpi_mode=false` → 走 FIFO/SE-DMA 路径。草案：

```c
proto = geni_se_read_proto(&gi2c->se);
if (proto == GENI_SE_INVALID_PROTO) {
    ret = geni_load_se_firmware(&gi2c->se, GENI_SE_I2C);
    if (ret) { dev_err_probe(dev, ret, "i2c firmware load failed ret: %d\n", ret); goto err_resources; }
} else if (proto != GENI_SE_I2C) {
    ret = dev_err_probe(dev, -ENXIO, "Invalid proto %d\n", proto);
    goto err_resources;
} else if (!of_property_read_bool(dev->of_node, "qcom,enable-gsi-dma") &&
           (readl_relaxed(gi2c->se.base + GENI_IF_DISABLE_RO) & FIFO_IF_DISABLE)) {
    /*
     * Bootloader pre-provisioned this SE in GSI/GPI-DMA mode, but DT does not
     * request GSI DMA. On QUP1 SE5 (i2c13 @a94000) GPI is broken for the
     * meizu-e3 touch/backlight slaves -> re-load SE firmware to fall back to FIFO.
     */
    ret = geni_load_se_firmware(&gi2c->se, GENI_SE_I2C);
    if (ret) { dev_err_probe(dev, ret, "i2c FIFO re-provision failed ret: %d\n", ret); goto err_resources; }
}
```

理由：`qcom,enable-gsi-dma`（DT）才是"期望模式"的唯一真相来源；HW 与之矛盾且可纠正时就纠正。触发面恰好只命中 `i2c13`（`i2c10` 有 flag → 跳过）。复用既有 `geni_load_se_firmware`，无新 DT 属性、无新固件。

**备选 A：从 dts 删 `dmas`/`dma-names`。** 否决——驱动模式由硬件 `FIFO_IF_DISABLE` 决定、非 `dmas`；删 `dmas` 只会让 `FIFO_IF_DISABLE` 置位时的 `setup_gpi_dma` 失败、`i2c13` probe 整体起不来，更糟。

**备选 B：改 compatible 为 `qcom,geni-i2c-master-hub`（`no_dma_support=true` 强制 FIFO）。** 否决——master-hub 是另一种 SE 块（无 `HW_PARAM_0` 寄存器、靠 `desc->tx_fifo_depth` 兜底），套在常规 QUP SE 上会错算 FIFO 深度。

**备选 C：unconditionally 对所有 i2c SE 调 `geni_load_se_firmware`。** 否决——会在已正常工作的 SE（如 `i2c10` RTC）上重载固件，副作用面过大；本决策仅在 mismatch 时触发，范围最小。

**备选 D：bootloader/QUP 固件把 SE5 provision 成 FIFO 或不预初始化。** 列为 Non-Goal——属固件侧、与"对齐 radxa rsdk"耦合，复杂度与回归面更大；保留为长期可选项。

### 决策 2：自动检测触发，不引入新 DT 属性（选定）

以"DT 无 `qcom,enable-gsi-dma` + HW `FIFO_IF_DISABLE` 置位"为触发条件，而非新增 `qcom,force-fw-reload` 之类 opt-in 属性。理由：语义即"DT 要 FIFO 但 HW 是 GSI"，本就该纠正；零 DT 改动、对未来其它同病 SE 自动生效。`patch 0003` 删 flag 的动作因此**仍是必需的**（它正是触发条件之一），保留。

## Risks / Trade-offs

- [在已 running 的 SE 上重调 `geni_load_se_firmware` 是否安全] → 该函数本就设计为完整重 provision（`geni_se_resources_on` 已在前置步骤打开、重写 SE RAM + proto + FIFO 位）；触发时机在 probe 早期、SE 尚无传输在途。Mitigation：仅 mismatch 触发；实板验证 `i2c10`/背光不回归。
- [`request_firmware("qcom/qcm6490/qupv3fw.elf")` 在 i2c probe 期失败/返回 `-EPROBE_DEFER`] → `.elf.zst` 已在 `/lib/firmware/qcom/qcm6490/`，`FW_LOADER_COMPRESS_ZSTD=y`。Mitigation：`-EPROBE_DEFER` 时让 probe 正常 defer 重试；构建侧确认固件随 rootfs 就位。
- [误伤其它 SE] → 仅当 DT 明确不要 GSI 且 HW 为 GSI 才触发；`i2c10` 因声明 `qcom,enable-gsi-dma` 被排除。Mitigation：实板逐 SE 复核。
- [上游可维护性] → 改动贴近上游 probe 结构、带解释性注释；如后续上游修正同问题可替换。

## Migration Plan

1. 新增 `patches/kernel/0006-i2c-geni-force-fifo-on-gsi-mismatch.patch`，纳入按序应用（`0001–0006`）。
2. `flange build kernel`（同 commit 重建注意既有 `reset_source` 已 `git clean -fd`）。
3. 验证：可先热插（`I2C_QCOM_GENI=m`：解绑 `sec_ts`/`sgm37604a` → `rmmod i2c_qcom_geni` → `insmod` 打补丁 `.ko`）做最小验证；再整体刷写。
4. 回滚：移除 `0006` patch 重建并刷写即恢复（纯内核侧、无固件改动，回滚安全）。

## Open Questions

- 是否同时把"为何 SE5 GSI 坏"作为独立 explore 留档（不阻塞本修复）。
- 长期是否更倾向走决策 D（固件侧 provision）以贴近上游/radxa 形态——可后续单独评估。
