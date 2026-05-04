# panel-firmware-build Specification

## Purpose

定义 flange 在构建期把可读的 panel init 序列文本源编译为 mainline `panel-mipi-dbi-spi` driver 兼容的 `panel.bin` 二进制 firmware、并按声明落入 rootfs `/lib/firmware/` 的契约。覆盖文本源语法、二进制头/条目格式、board 配置耦合点、错误处理。让"换屏 / 调 init seq"退化为编辑文本——不动内核、不动 driver。

## Requirements
### Requirement: Panel firmware 文本源契约

板级配置 MUST 通过文本源文件描述 `panel-mipi-dbi-spi` driver 所需的 init 序列，源文件落点 MUST 为 `components/board/<board>/firmware/panel/<name>.txt`。

文本源语法 MUST 支持以下三类行：

1. 注释行：以 `#` 起头，编码器忽略
2. 命令行：`command <CMD> [<P1> <P2> ...]`，`<CMD>` 与每个参数 MUST 是 `0x` 起头的两位十六进制字节字面量
3. 延迟行：`delay <MS>`，`<MS>` MUST 是 1..255 范围内的十进制毫秒数（mainline `panel-mipi-dbi-spi` driver 把 delay 编码为单字节参数，超过 255ms 需拆为多条 delay）

每行 MUST 是单一指令；空行允许且被忽略。

#### Scenario: 解析合法文本源
- **WHEN** 文本源包含
  ```
  # ST7789V SLPOUT
  command 0x11
  delay 120
  command 0x36 0x00
  ```
- **THEN** 编码器产出三条记录：cmd=0x11 无参、delay=120ms、cmd=0x36 参数 `[0x00]`

#### Scenario: 拒绝非法语法
- **WHEN** 文本源中出现 `command FF`（缺少 `0x` 前缀）或 `delay 99999`（超出 u16 范围）
- **THEN** 编码器 MUST 终止并报错，错误信息 MUST 指出行号与原因

### Requirement: Panel firmware 二进制格式契约

编码器 MUST 产出 mainline `drivers/gpu/drm/tiny/panel-mipi-dbi.c` （v5.18+）能正确解析的二进制：
- 16 字节 header：magic 15 字节 `"MIPI DBI" + 7 字节 0x00`，紧跟 1 字节 `file_format_version = 0x01`
- 命令条目 MUST 编码为 `{ cmd: u8, num_params: u8, params: u8[num_params] }`
- delay 指令 MUST 编码为上游约定的 NOP 特殊命令：`{ cmd: 0x00, num_params: 0x01, params: [ms_u8] }`
- 二进制 MUST 不包含尾随空字节或多余填充

编码器 MUST 提供单元测试，输入固定文本源、断言输出字节与上游 driver 加载预期一致。

#### Scenario: 编码器单元测试
- **WHEN** 单测输入一份包含命令、参数、延迟的最小文本源
- **THEN** 输出字节序列在 header、命令条目、delay 编码三个维度逐字节匹配预期

#### Scenario: 在板 driver 加载验证
- **WHEN** 把编码器产出的 `panel.bin` 部署到目标板 `/lib/firmware/panel/`，DTS 通过 `firmware-name` 引用
- **THEN** 内核 `panel-mipi-dbi-spi` driver MUST 成功 probe，dmesg MUST NOT 出现 firmware 解析错误

### Requirement: 构建期产出与 rootfs 落地

board 级构建 hook MUST 在 rootfs 准备阶段把所有声明的 panel firmware 文本源编译为 `.bin` 并落入 rootfs `lib/firmware/<dest>`。

board 配置 MUST 在 `rootfs.panel_firmware` 字段声明源 → 目标路径（相对 `/lib/firmware/`）的映射；未在配置中声明的 `.txt` 文件 MUST NOT 被自动编译落入 rootfs。

`<dest>` 路径 MUST 与板级 DTS overlay 中 panel 节点的最具体 `compatible` 字符串相符——mainline `panel-mipi-dbi-spi` driver 不读 `firmware-name` 属性，而是用 `<compatible[0]>.bin` 在 `/lib/firmware/` 根下查找；因此 `<dest>` 一般等同于 `<compatible[0]>.bin`（如 `panel-mipi-dbi-spi.bin`）。

#### Scenario: 声明式 firmware 编译
- **WHEN** board 配置声明 `rootfs.panel_firmware = [{"src": "firmware/panel/st7789v2-240x280.txt", "dest": "panel-mipi-dbi-spi.bin"}]`，且 board 的 DTS overlay 中 panel 节点 `compatible = "panel-mipi-dbi-spi"`
- **THEN** 构建期执行编码器，把 `components/board/<board>/firmware/panel/st7789v2-240x280.txt` 编为 `.bin`
- **AND** rootfs 中 `lib/firmware/panel-mipi-dbi-spi.bin` 存在且字节内容等于编码器输出
- **AND** 内核在板上请求 `panel-mipi-dbi-spi.bin` 时能命中该文件

#### Scenario: 源文件缺失
- **WHEN** board 配置声明的 `.txt` 源文件在 `components/board/<board>/firmware/panel/` 下不存在
- **THEN** 构建 MUST 失败，错误信息 MUST 指出缺失路径与所属 board

#### Scenario: 多个 board 互不干扰
- **WHEN** 两个 board 各自声明独立的 panel firmware
- **THEN** 各自 rootfs 仅包含本 board 声明的 `.bin`，互不污染

