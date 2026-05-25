## ADDED Requirements

### Requirement: Qualcomm EDL 刷写策略

`builder/flash.py` MUST 新增 `QualcommFlashStrategy`（实现 `FlashStrategy` 接口），通过 host 工具 `edl-ng` 在 Qualcomm EDL 模式下刷写，且不得改动现有 Rockchip/Allwinner/Amlogic 策略。

#### Scenario: 平台路由到 Qualcomm 策略

- **WHEN** flash 配置的 `platform` 为 `qualcommqcs6490`
- **THEN** 选用 `QualcommFlashStrategy`，其 `find_tool` 定位 `edl-ng`

#### Scenario: 不影响现有策略

- **WHEN** 平台为 rockchip/allwinnera733/amlogic
- **THEN** 仍使用各自原有策略，行为不变

### Requirement: 系统盘经 write-sector 刷 UFS

`QualcommFlashStrategy` 刷写系统镜像时 MUST 使用 `edl-ng --memory UFS write-sector 0 <raw.img>`（firehose loader 为 `prog_firehose_ddr.elf`），将 flange 产出的 GPT raw 镜像整盘写入 UFS。

#### Scenario: 写系统盘命令

- **WHEN** 刷系统镜像到 UFS
- **THEN** 调用 `edl-ng` 以 `--memory UFS` 与 `write-sector 0` 写入 raw 镜像，loader 为 `prog_firehose_ddr.elf`

### Requirement: SPI EDK2 固件单刷（bring-up）

`QualcommFlashStrategy` MUST 支持以 `edl-ng --loader prog_firehose_ddr.elf --memory spinor rawprogram rawprogram0.xml patch0.xml` 刷写 Radxa 预编 EDK2 SPI 固件（bring-up 一次性），与系统盘刷写分离。

#### Scenario: SPI 固件 rawprogram 刷写

- **WHEN** 执行 SPI EDK2 固件刷写
- **THEN** 以 `--memory spinor` + `rawprogram rawprogram0.xml patch0.xml` 经 firehose 刷入 SPI NOR

### Requirement: EDL 设备探测与诊断

`QualcommFlashStrategy.detect_device` MUST 探测处于 EDL 模式的 Qualcomm 设备（Qualcomm HS-USB QDLoader 9008）；未检测到时 MUST 给出"如何进入 EDL 模式（按钮 + USB3）"的明确诊断。

#### Scenario: 未进入 EDL 模式的诊断

- **WHEN** 未检测到 EDL 设备
- **THEN** 报错信息提示按住 EDL 按钮 + USB3 上电进入 EDL 模式
