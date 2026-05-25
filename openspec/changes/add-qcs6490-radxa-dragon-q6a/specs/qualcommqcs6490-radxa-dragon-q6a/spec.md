## ADDED Requirements

### Requirement: radxa-dragon-q6a board 配置基础字段

`components/board/radxa-dragon-q6a/config.py` MUST 导出 `BOARD` 字典并声明以下字段：

- `BOARD["board"]` MUST 等于 `"radxa-dragon-q6a"`
- `BOARD["soc"]` MUST 等于 `"qcs6490"`
- `BOARD["platform"]` MUST 等于 `"qualcommqcs6490"`
- `BOARD["kernel"]["dtb"]`（或等效 dtb 字段）MUST 指向 `qcs6490-radxa-dragon-q6a.dtb`

board config MUST NOT 覆盖 SoC 层的 `kernel.repo`/`kernel.branch`/`kernel.defconfig`/`bootloader`/`partitions`/`rootfs.url` 等字段，全部沿用 `components/platform/qualcommqcs6490/qcs6490/config.py`。

#### Scenario: 三层合并后 board 字段正确

- **WHEN** 调用 `get_board_config("radxa-dragon-q6a")`
- **THEN** `board`=`"radxa-dragon-q6a"`、`soc`=`"qcs6490"`、`platform`=`"qualcommqcs6490"`
- **AND** dtb 字段指向 `qcs6490-radxa-dragon-q6a.dtb`

#### Scenario: board 不覆盖 SoC 内核字段

- **WHEN** 调用 `get_board_config("radxa-dragon-q6a")`
- **THEN** `kernel.repo`/`kernel.branch`/`kernel.defconfig` 等于 SoC 层 `qcs6490` 的声明（`radxa/kernel.git` / `linux-6.18.2` / `qcom_module_defconfig`）

### Requirement: AIC8800 USB Wi-Fi 复用

`radxa-dragon-q6a` 的 Wi-Fi MUST 复用 AIC8800 USB 模组配置（与 `radxa-cubie-a7a` 同款固件与加载方式），不依赖 QCS6490 内置 ath11k。

#### Scenario: Wi-Fi 配置指向 AIC8800 USB

- **WHEN** 解析 board 的 wifi 配置
- **THEN** 启用 AIC8800 USB 固件与模块加载（与 a7a 一致）

### Requirement: lunch target 自动生成

`radxa-dragon-q6a` MUST 经现有 product/variant 机制自动生成 lunch target（如 `radxa-dragon-q6a-default-{debug,release}`），无需在 board config 之外额外注册。

#### Scenario: target 出现在有效列表

- **WHEN** 枚举有效 lunch targets
- **THEN** 列表包含 `radxa-dragon-q6a-default-debug` 与 `radxa-dragon-q6a-default-release`
