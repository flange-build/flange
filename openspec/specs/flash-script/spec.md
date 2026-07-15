# flash-script Specification

## Purpose
TBD - created by archiving change 2026-03-29-phase6-image-flash. Update Purpose after archive.
## Requirements
### Requirement: 刷写主入口脚本
`scripts/flange-flash.sh` SHALL 作为宿主机刷写的主入口脚本，解析命令行参数，从 `target/<board>/image/` 读取产物，调用平台对应的刷写模块执行操作。

#### Scenario: 整盘 dd 刷写
- **WHEN** 执行 `./scripts/flange-flash.sh --board radxa-zero3w --raw --device /dev/sdX`
- **THEN** 将 `target/radxa-zero3w/image/raw.img` 通过 dd 写入 `/dev/sdX`

#### Scenario: USB 分段刷写
- **WHEN** 执行 `./scripts/flange-flash.sh --board radxa-zero3w`
- **THEN** 调用平台对应的刷写工具（Rockchip: rkdeveloptool）按分区刷写各组件

#### Scenario: 组件级刷写
- **WHEN** 执行 `./scripts/flange-flash.sh --board radxa-zero3w --component kernel`
- **THEN** 仅刷写 boot 分区（包含内核和 DTB）

#### Scenario: 产物目录不存在
- **WHEN** `target/<board>/image/` 目录不存在
- **THEN** 输出错误信息提示先执行构建和收集

### Requirement: 平台刷写模块化架构
刷写脚本 SHALL 采用模块化架构，平台刷写逻辑通过 `scripts/flash/<platform>.sh` 实现，主脚本通过 source 加载。

#### Scenario: Rockchip 平台刷写模块
- **WHEN** 检测到目标板为 Rockchip 平台
- **THEN** 加载 `scripts/flash/rockchip.sh` 执行刷写

#### Scenario: 新增平台支持
- **WHEN** 需要支持 Allwinner 平台刷写
- **THEN** 只需新增 `scripts/flash/allwinner.sh`，无需修改主脚本

### Requirement: 刷写工具检测
刷写脚本 SHALL 在执行前检测所需的刷写工具是否已安装，未安装时提供安装指引。

#### Scenario: rkdeveloptool 未安装
- **WHEN** Rockchip 平台刷写时宿主机未安装 `rkdeveloptool`
- **THEN** 输出错误信息并提示安装方法

#### Scenario: dd 工具检查
- **WHEN** 使用 `--raw` 模式刷写
- **THEN** 检查 dd 命令可用（通常系统自带）

### Requirement: 刷写安全确认
刷写脚本 SHALL 在执行破坏性写入操作前要求用户确认，防止误刷错误设备。

#### Scenario: dd 刷写确认
- **WHEN** 执行 `--raw --device /dev/sdX` 刷写
- **THEN** 显示目标设备信息并要求用户输入确认

#### Scenario: USB 刷写设备检测
- **WHEN** 执行 USB 分段刷写
- **THEN** 检测目标设备是否处于 Maskrom/Loader 模式，未检测到时提示用户操作

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

