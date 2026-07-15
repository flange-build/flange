# flash-script Specification

## Purpose

定义由 Python flash config、平台策略和执行器完成的镜像选择、设备发现、写前安全校验，
以及全量、组件级和整盘模式的宿主机设备刷写契约。

## Requirements
### Requirement: 刷写主入口脚本

宿主机刷写主入口 SHALL 为 `flange flash`，由 `builder.flash` 的 Python CLI 读取 `.build/target/<board>/<product>/<variant>/flash-config.json` 并执行；不得依赖已删除的 `scripts/flange-flash.sh`。构建时生成的 flash config SHALL 冻结平台、目标和分区到镜像映射，使 target 目录可独立搬运到另一台宿主机刷写。

#### Scenario: 整盘 dd 刷写

- **WHEN** 执行 `flange flash --raw --device /dev/sdX`
- **THEN** `FlashExecutor` 在确认后把 target 中的整盘镜像写入指定设备

#### Scenario: USB 全量刷写

- **WHEN** 执行 `flange flash`
- **THEN** Python 平台策略按 flash-config 的分区顺序写入全部适用镜像并按选项重启设备

#### Scenario: 组件级刷写

- **WHEN** 执行 `flange flash rootfs`
- **THEN** 只写 flash-config 中名为 rootfs 的分区

#### Scenario: flash config 不存在

- **WHEN** 当前 target 目录缺少 `flash-config.json`
- **THEN** 命令在接触设备前失败并提示先构建 image

### Requirement: 平台刷写模块化架构

刷写逻辑 SHALL 采用 Python strategy（策略）架构：`FlashExecutor` 负责通用流程，`FlashStrategy` 子类负责工具发现、设备检测、pre-flash、分区写入和重启；平台通过注册表选择策略。新增平台 SHALL 通过增加对应 Python strategy 接入，不得恢复 source shell 模块机制。

#### Scenario: Rockchip 平台刷写策略

- **WHEN** flash-config 的 platform 为 rockchip
- **THEN** 执行器选择 `RockchipFlashStrategy` 并调用匹配宿主系统的 upgrade_tool

#### Scenario: 新增平台注册

- **WHEN** 新平台实现 `FlashStrategy` 并加入策略注册表
- **THEN** `FlashExecutor` 可按 flash-config platform 选择该实现而无需修改通用刷写流程

### Requirement: 刷写工具检测

平台 strategy SHALL 在写入前定位并校验所需宿主工具；工具不存在或不可执行时 SHALL 在连接/写入设备前失败，并给出工具名称与解决指引。

#### Scenario: upgrade_tool 不存在

- **WHEN** Rockchip target 对应宿主工具路径不存在
- **THEN** `flange flash` 抛出 `FlashError` 且不执行任何设备写入命令

#### Scenario: dd 整盘模式

- **WHEN** 用户选择 raw 模式
- **THEN** 执行器使用宿主 dd/sync 路径，并在命令失败时传播非零结果

### Requirement: 刷写安全确认

刷写执行器 SHALL 在破坏性整盘写入前要求明确确认，并在 USB 分区刷写前检测或等待目标设备进入支持模式。未知分区、缺失镜像、设备歧义或等待超时 MUST 在写入前失败。

#### Scenario: dd 刷写确认

- **WHEN** 执行 `--raw --device /dev/sdX`
- **THEN** 显示目标设备与镜像，并仅在用户确认后执行 dd

#### Scenario: USB 刷写等待设备

- **WHEN** 执行 USB 刷写且设备尚未进入 MaskROM/Loader 模式
- **THEN** strategy 在配置的超时内轮询等待，超时后报错且不写入

#### Scenario: 未知分区名

- **WHEN** 执行 `flange flash <name>` 且 flash-config 无该分区
- **THEN** 本地校验失败并列出可用分区，不调用平台写入工具

### Requirement: Rockchip SPI NAND 按 GPT 配置的具名分区刷写

当 flash config 声明 `storage_type=spinand` 时，Rockchip flash strategy SHALL 在全量刷写时
强制只连接一台设备；MaskROM 下先用 `DB` 临时启动 miniloader，以 `RCI/RFI/RID` 核对 SoC 与
存储身份，随后执行 `UL miniloader -noreset`，再执行由 GPT entries 生成的
`DI -p parameter.txt`，
随后按刷写清单向具名 uboot、boot、amp、rootfs 等分区写入对应镜像；SHALL NOT 执行
`DI -idbloader`。普通单分区刷写在 MaskROM 模式 MAY 用 `DB` 临时下载 miniloader，在 Loader
模式 SHALL 复用当前 loader；但 `flange flash bootloader` SHALL 先用 `UL -noreset` 持久更新
loader/SPL，再写具名 uboot proper。若配置显式
声明 `storage` selector，strategy SHALL 依据 `upgrade_tool SSD` 列表选择介质；若 selector 为空，
strategy SHALL 保持 loader 当前介质且不得调用 `SSD`。全量与组件级刷写 SHALL 复用相同的分区映射。

#### Scenario: 全量 SPI NAND 刷写顺序正确
- **WHEN** 对处于 MaskROM 的 ATK-RK3506B 执行全量 `flange flash`
- **THEN** 命令顺序为临时 `DB`、身份核验、`UL miniloader -noreset`、下发 parameter、逐分区写入、重启
- **AND** 不调用 `DI -idbloader`
- **AND** 不调用 `upgrade_tool SSD`
- **AND** 不调用宿主机 `dd` 写整片 NAND

#### Scenario: 单刷 AMP 不重写其他分区
- **WHEN** 执行 `flange flash amp`
- **THEN** 只向名为 `amp` 的分区写入 `amp.img`
- **AND** boot 与 rootfs 分区保持不变

#### Scenario: 显式存储介质不存在时安全失败
- **WHEN** 多介质 target 显式配置的存储名称不在 `upgrade_tool SSD` 列表中
- **THEN** 刷写在下发 parameter 或写分区前失败
- **AND** 错误包含工具报告的可选介质列表

#### Scenario: 单介质 loader 不支持 SSD
- **WHEN** SPI NAND target 未配置 storage selector，且 loader 的 `SSD` 命令不具备该能力
- **THEN** strategy 不执行 `SSD`，直接对 loader 当前介质执行 parameter 与具名 DI 流程

### Requirement: SPI NAND 刷写前校验分区和镜像

flash strategy SHALL 在执行写入前验证生成的 `parameter.txt`、分区名称、镜像存在性和镜像容量。
rootfs 的 MTD index MUST 与配置/DTS 的 `ubi.mtd` 一致；任一不一致 SHALL 阻止刷写。
flash config SHALL 保存 parameter SHA-256，并从同一份已解析 parameter 派生每个分区的
name/offset/size；preflight SHALL 同时校验摘要和逐项布局。
SPI NAND flash config 若仍把 `idbloader` 列为具名 DI 分区，strategy SHALL 将其视为旧版构建
产物，并在连接设备或执行 loader 命令前要求重新构建 image。

#### Scenario: rootfs index 与 ubi.mtd 不一致
- **WHEN** parameter 中 rootfs 不是 `mtd5` 但目标 DTS 声明 `ubi.mtd=5`
- **THEN** 刷写前校验失败且不写入设备

#### Scenario: 分区镜像超过容量
- **WHEN** boot、amp 或 rootfs 镜像大于目标分区
- **THEN** 刷写前失败并指出镜像与分区大小

#### Scenario: 旧版 SPI NAND 清单在碰设备前失败
- **WHEN** SPI NAND flash config 的具名分区仍包含 `idbloader`
- **THEN** 本地 preflight 提示执行 `flange build image -f`
- **AND** 不调用 `UL`、`DI` 或其他设备命令

#### Scenario: parameter 与 flash config 漂移时失败
- **WHEN** parameter 摘要或任一分区 offset/size 与 flash config 不一致
- **THEN** preflight 在连接设备前失败并要求重新构建 image
