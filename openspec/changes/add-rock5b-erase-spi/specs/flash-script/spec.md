## ADDED Requirements

### Requirement: 独立擦除 Rockchip SPI NOR

宿主机 SHALL 提供 `flange flash --erase-spi`，在 Rockchip 设备上显式选择并确认 SPINOR 后
擦除全部 SPI NOR 内容；不得继续执行系统分区刷写。普通刷写 SHALL 保持既有行为。
操作 SHALL 使用当前 target 的 flash-config 和 miniloader，不要求存在系统镜像。

#### Scenario: ROCK 5B 处于 MaskROM
- **WHEN** 当前目标为 ROCK 5B 且唯一设备处于 MaskROM，执行 `flange flash --erase-spi`
- **THEN** 校验 loader 文件、下载 loader、核对 SoC、切换并确认 SPINOR、执行 EF，由工具自身复位，SHALL NOT 再追加 RD

#### Scenario: Loader 模式
- **WHEN** 设备处于 Loader 且指定 `--erase-spi --no-wait`
- **THEN** 只探测一次设备，跳过 DB，完成 SPI 擦除后不执行 RD

#### Scenario: 拒绝不安全目标或执行失败
- **WHEN** 平台不支持、loader 缺失、设备缺失或不唯一、SoC 不匹配、SPINOR 不可选或未激活，或 EF 失败
- **THEN** 命令报告失败并停止后续动作，不改写其他介质，不显示擦除成功

#### Scenario: 参数互斥
- **WHEN** `--erase-spi` 与分区名、`--raw`、`--list`、`--spi-firmware` 或 `--provision-ufs` 同时指定
- **THEN** 在访问设备前报告参数冲突

#### Scenario: 存储列表通过 Q 正常退出但返回非零值
- **WHEN** SSD 列表查询已返回有效列表，但输入 Q 退出时返回非零值
- **THEN** SHALL 按列表内容选择 SPINOR，并在实际切换成功且再次确认 SPINOR 激活后才执行 EF
- **THEN** 缺少 SPINOR、无法确认激活或实际切换失败时仍 SHALL 停止擦除

#### Scenario: 拒绝禁止复位选项
- **WHEN** 指定 `--erase-spi --no-reboot`
- **THEN** SHALL 在访问设备前报错，说明 EF 自带复位、不支持禁止复位
