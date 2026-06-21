## ADDED Requirements

### Requirement: Qualcomm edl-ng 刷写策略

`builder/flash.py` MUST 新增 `QualcommQrb2210FlashStrategy`（继承 Q6A 的 `QualcommFlashStrategy`、复用同一份 host 工具 `edl-ng`），在 Qualcomm EDL 模式下刷写，且不得改动现有 Rockchip/Allwinner/Amlogic/qualcommqcs6490 策略。

#### Scenario: 平台路由到 QRB2210 策略

- **WHEN** flash 配置的 `platform` 为 `qualcommqrb2210`
- **THEN** 选用 `QualcommQrb2210FlashStrategy`，其 `find_tool` 定位 `edl-ng`（`tools/<os>/edl-ng/edl-ng` 或 PATH）

#### Scenario: 不影响现有策略

- **WHEN** 平台为 rockchip/allwinnera733/amlogic/qualcommqcs6490
- **THEN** 仍使用各自原有策略，行为不变

### Requirement: 按分区刷 boot/rootfs 到 eMMC

`QualcommQrb2210FlashStrategy` 刷写系统时 MUST 使用 `edl-ng --loader <firehose loader> --memory emmc rawprogram <flange rawprogram>.xml`，仅将 `boot`（vendor label `efi`）与 `rootfs` 写入 vendor 固定 GPT 的既有槽位。MUST NOT 整盘 `write-sector`、MUST NOT 重写 vendor GPT。flange rawprogram 用 basename 引用镜像，刷写前 MUST 在临时目录建 `boot.img`/`rootfs.img` 符号链接供 edl-ng 同目录定位。

#### Scenario: 按分区写命令

- **WHEN** 刷系统到 eMMC
- **THEN** 调用 `edl-ng` 以 `--memory emmc rawprogram <flange rawprogram>.xml` 写入，仅 `boot`/`rootfs` 落盘，vendor 分区保留

### Requirement: vendor bootloader 固件单刷（bring-up）

`QualcommQrb2210FlashStrategy` MUST 支持以 `edl-ng --loader <firehose loader> --memory emmc rawprogram <vendor rawprogram*.xml> <patch*.xml>` 刷写 Arduino/armbian 预编的 vendor bootloader 固件（XBL/ABL/TZ/HYP/U-Boot boot.img/GPT，bring-up 一次性），与按分区的系统刷写分离，复用 CLI `--spi-firmware` 入口。

#### Scenario: vendor 固件 rawprogram 刷写

- **WHEN** 执行 vendor bootloader 固件刷写
- **THEN** 以 `--memory emmc rawprogram` + vendor `rawprogram*.xml`/`patch*.xml` 经 firehose（`prog_firehose_ddr.elf`）刷入 eMMC

### Requirement: EDL 设备探测与诊断

`QualcommQrb2210FlashStrategy.detect_device` MUST 探测处于 EDL 模式的 Qualcomm 设备（Qualcomm HS-USB QDLoader 9008，VID:PID `05c6:9008`，复用 Q6A 被动 USB 探测）；未检测到时 MUST 给出"如何进入 EDL 模式（JCTL 跳线）"的明确诊断。

#### Scenario: 未进入 EDL 模式的诊断

- **WHEN** 未检测到 EDL 设备
- **THEN** 报错信息提示用 JCTL 跳线进入 EDL 模式

#### Scenario: 未找到 edl-ng 的诊断

- **WHEN** host 上找不到 `edl-ng`
- **THEN** 报错信息提示预期路径 `tools/<os>/edl-ng/edl-ng` 或 PATH
