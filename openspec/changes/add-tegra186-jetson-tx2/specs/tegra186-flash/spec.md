## ADDED Requirements

### Requirement: 构建期生成自包含 tegraflash 刷写包
image 组件 SHALL 在 `image/tegraflash-bundle/` 生成刷写包：由 BSP 分区模板与配置 token 表生成的 `flash.xml`、
全部启动链文件、flange 的 `boot.img` / `kernel-dtb` / `system.img`、按 flash.sh 格式生成的 `emmc_bootblob_ver.txt`，
以及记录 tegraflash 参数、分区列表、EEPROM 身份期望和每个文件 SHA256 的 `manifest.json`。
`system.img` SHALL 由 rootfs 扩展到 APP 分区大小后转为稀疏格式。L4T OTA recovery 相关分区 SHALL 保留但不写入文件。
image 组件 SHALL NOT 产出 `raw.img`。

#### Scenario: 与参考 flash.xml 对照
- **WHEN** 使用与参考刷写相同的 BSP 与板级配置构建 image
- **THEN** 生成的 `flash.xml` 与 flash.sh 生成的参考文件只在 APP 尺寸、kernel-dtb 文件名与 recovery 三个分区的文件名上不同

#### Scenario: 与参考 flashcmd 对照
- **WHEN** 生成刷写包
- **THEN** manifest 中的全量刷写参数与参考 `flashcmd.txt` 的参数一致

#### Scenario: rootfs 超出 APP 分区
- **WHEN** rootfs 镜像大于板级配置的 APP 分区尺寸
- **THEN** image 构建失败并给出两者大小

### Requirement: flash-config 只使用现有字段
`nvidiategra186` 的 FlashPlan SHALL 通过 `generate_flash_config` 生成 flash-config.json，
使用 `platform`、`partitions`、`pre_flash.usb_vid/usb_pid`（`0955:7c18`）与 `bundle_manifest(_sha256)`，不新增 FlashConfig 字段。
分区列表来自生成的 `flash.xml`，`APP` 与 `kernel-dtb` 以外的分区 SHALL 标记为受保护。

#### Scenario: 分区列表
- **WHEN** 执行 `flange flash --list`
- **THEN** 输出 `flash.xml` 中带文件的分区，`APP` 与 `kernel-dtb` 未受保护，其余受保护

### Requirement: 宿主刷写前完成本地与设备身份核对
`tegraflash` 刷写策略 SHALL 在任何写入前：确认宿主为 x86_64 Linux；按 manifest 复核刷写包全部文件 SHA256；
通过 sysfs 检测恰好一台 `0955:7c18` 设备；用 `dump eeprom boardinfo` 读取模块 EEPROM 并用 `chkbdinfo` 解析，
board ID、SKU、FAB 与 manifest 期望一致。任一检查失败 SHALL 以 `FlashError` 终止且不写入设备。
tegraflash SHALL 在刷写包的临时副本中运行，结束后清理。

#### Scenario: 非 x86_64 宿主
- **WHEN** 在 macOS 或 ARM Linux 上执行 `flange flash`
- **THEN** 命令在检测设备前失败，说明 tegraflash 宿主工具只支持 x86_64 Linux

#### Scenario: 刷写包被篡改
- **WHEN** 刷写包中任一文件的 SHA256 与 manifest 不符
- **THEN** 刷写在检测设备前失败并列出不一致的文件

#### Scenario: 多台 Recovery 设备
- **WHEN** 宿主上存在两台 `0955:7c18` 设备
- **THEN** 刷写拒绝继续并提示只保留一台

#### Scenario: 模块身份不符
- **WHEN** EEPROM 读出的 board ID 为 `3489`
- **THEN** 刷写在写入前失败，错误同时给出期望值与实际值

### Requirement: 全量刷写与按分区刷写
全量刷写 SHALL 以 manifest 参数调用 `tegraflash.py --cmd "flash; reboot"`。按分区刷写 SHALL 只接受 manifest 中带文件的分区：
带 `oem_sign` 的分区使用 `signwrite <分区> <文件>`，其余使用 `write`，并追加 `reboot`；受保护分区需要显式允许。
按 offset 写入与 `--raw` 整盘模式 SHALL 明确拒绝。

#### Scenario: 单刷 rootfs
- **WHEN** 执行 `flange flash APP`
- **THEN** 策略在身份核对后执行 `write APP system.img; reboot`，不写入其他分区

#### Scenario: 单刷受保护分区
- **WHEN** 未显式允许时执行 `flange flash cpu-bootloader`
- **THEN** 刷写拒绝并说明该分区受保护

#### Scenario: 整盘模式
- **WHEN** 执行 `flange flash --raw /dev/sdX`
- **THEN** 命令失败并提示该平台没有 `raw.img`，应使用 `flange flash`
