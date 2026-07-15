## RENAMED Requirements

- FROM: `### Requirement: amp 分区必须声明为非 raw 具名 GPT 分区`
- TO: `### Requirement: amp 分区必须声明为目标存储可寻址的具名 GPT 分区`
- FROM: `### Requirement: image 整盘组装把 amp.img dd 进 amp 分区偏移`
- TO: `### Requirement: image 与 flash 按存储能力处理 amp.img`

## MODIFIED Requirements

### Requirement: amp 分区必须声明为目标存储可寻址的具名 GPT 分区

启用 AMP 的配置 SHALL 在 `partitions.entries` 中声明名为 `amp` 的非 raw GPT 条目，使 U-Boot
可通过 `part_get_info_by_name(dev_desc, "amp", ...)` 定位 FIT。amp 条目仅以 partition type
占位，不执行 `mkfs`；其位置 SHALL 在 rootfs 之前。SPI NAND target SHALL 复用同一 GPT
配置模型，不得另行复制板外 MTD parameter。

#### Scenario: amp 分区以名 "amp" 出现在 GPT
- **WHEN** 构建启用 AMP 的 GPT target 并解析 `raw.img` 分区表
- **THEN** 存在名为 `amp` 的非 raw GPT 条目
- **AND** 起始偏移等于配置中 amp 条目的 offset

#### Scenario: GPT 拒绝 raw 类型的 amp 分区
- **WHEN** GPT target 的 amp 分区声明为 `type=raw`
- **THEN** 配置校验失败并说明 GPT AMP loader 需要具名 GPT 条目

#### Scenario: SPI NAND parameter 继承同一 amp 条目
- **WHEN** 从 SPI NAND target 的 GPT entries 生成 `parameter.txt`
- **THEN** parameter 中存在同名、同 offset、同 size 的 amp 分区
- **AND** ATK-RK3506B 的 amp 位于 `mtd4`、rootfs 位于 `mtd5`

#### Scenario: amp 分区不被格式化
- **WHEN** 任一 GPT 存储模式写入 amp 分区
- **THEN** 不调用文件系统 mkfs
- **AND** 写入后的分区起始数据为合法 FIT

### Requirement: image 与 flash 按存储能力处理 amp.img

`builder/platforms/rockchip/image.py` SHALL 对块设备 GPT target 在 AMP 启用时按 amp 分区 offset
把 `amp.img` 写入逻辑 `raw.img`；AMP 未启用或无产物时 SHALL 跳过。
`storage.type=spinand` 的 target MUST 只生成具名刷写 manifest，并使用 `DI -amp` 写入。

#### Scenario: 块设备 GPT raw.img 在 amp 偏移含 amp.img
- **WHEN** 非 SPI NAND 的 GPT target 启用 AMP 并构建 image
- **THEN** `raw.img` 在 amp 分区偏移处等于 `amp.img` FIT 数据

#### Scenario: GPT target 关闭 AMP 时跳过写入
- **WHEN** GPT target 的 AMP 关闭且无 `amp.img`
- **THEN** 整盘组装不写入 amp 分区且 image 构建成功

#### Scenario: SPI NAND 单刷 amp 使用具名 DI
- **WHEN** 对 GPT/SPI NAND target 执行 `flange flash amp`
- **THEN** 刷写命令为具名 `DI -amp amp.img`
- **AND** 不使用物理 offset 的 WL 或整片 raw 写入

#### Scenario: SPI NAND 不生成逻辑 raw.img
- **WHEN** `storage.type=spinand` 的 target 构建 image
- **THEN** 输出 parameter 与具名刷写 manifest
- **AND** 不生成或缓存 `raw.img`

### Requirement: validate_amp 校验 amp 配置自洽

`builder/config/validate.py` SHALL 在 `config.amp.enabled` 为真时断言 mode 为 `hal` 或
`rt-thread`、目标 CPU/内存布局完整，并要求非 raw amp GPT 分区位于 rootfs 之前且容量不小于
`amp.img` 最大配置值。任一不满足 SHALL 给出明确错误。

#### Scenario: 启用 amp 但缺 amp 分区
- **WHEN** `config.amp.enabled=true` 但最终 GPT 布局无 amp 分区
- **THEN** 配置校验失败，错误指明缺少 amp 分区

#### Scenario: 非法 mode
- **WHEN** `config.amp.mode` 不是 `hal` 或 `rt-thread`
- **THEN** 配置校验失败，错误指明合法取值

#### Scenario: amp 分区排在 rootfs 之后
- **WHEN** GPT amp 分区位于 rootfs 之后
- **THEN** 配置校验失败
