## ADDED Requirements

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
