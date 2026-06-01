## Why

`radxa-dragon-q6a-meizu-e3-bringup` 产物在 linux-7.0.2 基线上触摸（`sec_ts`）完全不响应。实板已确诊根因：触摸/背光所在 `i2c13`（QUP1 SE5 `@a94000`）被 bootloader（对齐 radxa rsdk）预 provision 成 I2C-GSI/GPI-DMA 模式（`FIFO_IF_DISABLE` 置位），而 GPI 对该 SE 失败（`gpi a00000 Error in Transaction` / `not enough space in ring` / `prep_slave_sg failed`）。7.0.2 的 `i2c-qcom-geni.c` probe 在读到 `proto==I2C`（SE 已被 bootloader 初始化）时**跳过** `geni_load_se_firmware()`，而 `qcom,enable-gsi-dma` 的唯一读取点恰在该函数内——于是现有 `patches/kernel/0003`（从 dts 删 `qcom,enable-gsi-dma`）在 7.0.2 形同死代码，SE 仍停留在 GSI。结果：`sec_ts` device id 读成 `0,0,0`（应 `AC,6F,70`）、触摸坐标读不出、屏触摸不可用。芯片本身正常（已上电解复位、触摸时 IRQ189 计数累增）。

## What Changes

- 新增 kernel patch `components/platform/qualcommqcs6490/patches/kernel/0006-i2c-geni-force-fifo-on-gsi-mismatch.patch`（改 `drivers/i2c/busses/i2c-qcom-geni.c`）：当某 i2c SE 的 DT **未**声明 `qcom,enable-gsi-dma`、但 probe 时该 SE 起来是 GSI（`proto==GENI_SE_I2C` 且 `GENI_IF_DISABLE_RO & FIFO_IF_DISABLE` 置位）时，强制再调一次 `geni_load_se_firmware(GENI_SE_I2C)` 把 SE 重 provision 回 FIFO。
- 保留 `0003`（删 `qcom,enable-gsi-dma`）作为 DT 侧"要 FIFO"的意图声明；新 patch 让该意图在 7.0.2 bootloader 预初始化场景下真正生效。
- 更正 `qcs6490-mainline-kernel` 规格中"删 `qcom,enable-gsi-dma` 即回退 FIFO"的失效结论，并同步更正 `wiki/boards/radxa-dragon-q6a.md` 坑#11。
- 作用域严格限定 `i2c13`/SE5 触发条件；`i2c10`（RTC，DT 声明 `qcom,enable-gsi-dma`、GSI 正常）与其它 SE 行为不变；`default` 产物 `i2c13` 无从机、零副作用。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `qcs6490-mainline-kernel`: "魅族 E3 屏（meizu-e3-bringup product）在 mainline 重验通过"要求中关于触摸/背光 i2c 的部分须更正——`i2c13` 走 FIFO **不能仅靠**从 dts 删 `qcom,enable-gsi-dma`；在 7.0.2（bootloader 预 provision SE 为 GSI、geni i2c probe 因 `proto` 已初始化而跳过固件重载）下，SHALL 由内核 patch 在"DT 未要 GSI 但 SE 起来是 GSI"时强制重 provision 回 FIFO。触摸/背光 i2c 读写成功、`sec_ts` 出 `AC,6F,70`、无 `GPI transfer failed` 的判定标准不变；"按序应用 patch"场景由 0001–0005 扩到 0001–0006。

## Impact

- **代码**：新增 `components/platform/qualcommqcs6490/patches/kernel/0006-*.patch`；内核 patch 序列 `0001–0005` → `0001–0006`。
- **文档**：`wiki/boards/radxa-dragon-q6a.md` 坑#11 更正；根因已记入记忆 `qcs6490-touch-i2c13-gsi-fifo`。
- **产物**：`radxa-dragon-q6a-meizu-e3-bringup-*` 触摸恢复可用；`default` 产物不受影响。
- **验证**：需 `flange build kernel` + 刷写（或热插 `i2c-qcom-geni.ko`，`I2C_QCOM_GENI=m`）实板验证。
- **风险**：在已 running 的 SE 上重调 `geni_load_se_firmware` 的安全性、触发条件不误伤 `i2c10`/其它 SE——在 design 中评估，触发面最小化（仅 mismatch）。

## 非目标

- 不修改 bootloader/XBL/QUP 固件的 SE provision 表（保持对齐 radxa rsdk，不引入固件侧改动）。
- 不深究"为何 SE5 的 GSI 路径本身坏"（对照组 SE3/`i2c10` 的 GSI 正常）——改用 linux-6.18.2 已实板证明可用的 FIFO 模式，不修 GPI/GSI。
- 不改 `i2c10`（RTC）及其它 SE 现有的 GSI/DMA 行为。
- 不涉及 `panel_meizu_e3` 显示与 `sgm37604a` 背光的功能新增，仅确保本改动不使其回归。
