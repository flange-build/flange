## ADDED Requirements

### Requirement: arduino-uno-q board 配置基础字段

`components/board/arduino-uno-q/config.py` MUST 导出 `BOARD` 字典并声明以下字段：

- `BOARD["board"]` MUST 等于 `"arduino-uno-q"`
- `BOARD["soc"]` MUST 等于 `"qrb2210"`
- `BOARD["platform"]` MUST 等于 `"qualcommqrb2210"`
- `BOARD["kernel"]["dtb"]`（或等效 dtb 字段）MUST 指向 `qrb2210-arduino-imola.dtb`

board config MUST NOT 覆盖 SoC 层的 `kernel.repo`/`kernel.branch`/`kernel.defconfig`/`bootloader`/`partitions`/`rootfs.url` 等字段，全部沿用 `components/platform/qualcommqrb2210/qrb2210/config.py`。

#### Scenario: 三层合并后 board 字段正确

- **WHEN** 调用 `get_board_config("arduino-uno-q")`
- **THEN** `board`=`"arduino-uno-q"`、`soc`=`"qrb2210"`、`platform`=`"qualcommqrb2210"`
- **AND** dtb 字段指向 `qrb2210-arduino-imola.dtb`

#### Scenario: board 不覆盖 SoC 内核字段

- **WHEN** 调用 `get_board_config("arduino-uno-q")`
- **THEN** `kernel.repo`/`kernel.branch`/`kernel.defconfig` 等于 SoC 层 `qrb2210` 的声明（mainline `linux` / `v7.0` / arm64 `defconfig`）

### Requirement: lunch target 自动生成

`arduino-uno-q` MUST 经现有 product/variant 机制自动生成 lunch target（如 `arduino-uno-q-default-{debug,release}`），无需在 board config 之外额外注册。

#### Scenario: target 出现在有效列表

- **WHEN** 枚举有效 lunch targets
- **THEN** 列表包含 `arduino-uno-q-default-debug` 与 `arduino-uno-q-default-release`
