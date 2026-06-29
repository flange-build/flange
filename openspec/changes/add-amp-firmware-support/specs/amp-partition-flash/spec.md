## ADDED Requirements

### Requirement: amp 分区必须声明为非 raw 具名 GPT 分区

启用 amp 的配置 SHALL 在 `partitions.entries` 中声明一个 `name` 为 `"amp"` 的分区，且其 `type` SHALL 为非 raw 类型（如 `"ext4"`，仅作 GPT 类型 GUID 占位，构建过程不对其执行 `mkfs`）。amp 分区 SHALL NOT 声明为 `type: "raw"`。该 amp 分区 SHALL 为 **product 作用域**（如 tspi-rk3566 经 board 配置的 `"partitions:amp"` 条件键整块覆盖分区表），SHALL NOT 改动 SoC 层共享分区表——否则同 SoC 的非 amp product（如 `default`）也会被插入 amp 分区、rootfs offset 偏移，违背「default product 不受影响」。理由：U-Boot 的 AMP loader 以 `part_get_info_by_name(dev_desc, "amp", ...)` 按 GPT 分区**名**定位固件，而 `builder/platforms/rockchip/image.py` 对 `type == "raw"` 的分区跳过建立 GPT 条目（仅 dd 不入表）——声明 raw 会使 U-Boot 永远 `-ENODEV`、从核不被拉起。

#### Scenario: amp 分区以名 "amp" 出现在 GPT

- **WHEN** 构建出 `image` 并解析 `raw.img` 的 GPT 分区表
- **THEN** 存在一个分区名为 `amp` 的 GPT 条目
- **AND** 其起始偏移等于 `partitions.entries` 中 amp 条目声明的 offset

#### Scenario: 拒绝 raw 类型的 amp 分区

- **WHEN** amp 分区被声明为 `type: "raw"`
- **THEN** 配置校验失败（amp 必须为非 raw 具名分区）

#### Scenario: amp 分区不被格式化

- **WHEN** 整盘组装写入 amp 分区
- **THEN** `parted` 写出名为 `amp` 的 GPT 条目但不对其执行 `mkfs`
- **AND** dd 进该偏移的裸 FIT 块原样保留，`fdt_check_header` 通过

### Requirement: image 整盘组装把 amp.img dd 进 amp 分区偏移

`builder/platforms/rockchip/image.py` 的 `PARTITION_IMAGES` SHALL 新增 `"amp": "amp/amp.img"`，使整盘组装按 amp 分区的偏移把 `amp.img` dd 进 `raw.img`。amp 未启用或无产物时，整盘组装 SHALL 跳过 amp 分区写入（不报错）。

#### Scenario: raw.img 在 amp 偏移含 amp.img

- **WHEN** amp 启用并构建 `image`
- **THEN** `raw.img` 在 amp 分区偏移处的内容等于 `amp/amp.img` 的 FIT 数据

#### Scenario: amp 未启用时整盘组装跳过 amp 分区

- **WHEN** amp 关闭（无 `amp/amp.img`）并构建 `image`
- **THEN** 整盘组装不写入 amp 分区，`image` 构建成功

### Requirement: 刷写映射识别 amp 分区

`builder/flash.py` 的 `RockchipFlashStrategy.partition_image_map` SHALL 新增 `"amp": "amp/amp.img"`（并以 `amp.enabled` 作为 gate，仿 recovery），使 `FlashConfigGenerator` 生成的 `flash-config.json` 含 amp 分区。`flange flash`（全量）SHALL 写入 amp.img，`flange flash amp`（单刷）SHALL 仅写 amp 分区，`flange flash --list` SHALL 列出 amp。

#### Scenario: flash-config.json 含 amp

- **WHEN** amp 启用并构建 `image`
- **THEN** 生成的 `flash-config.json` 含 amp 分区条目，其镜像指向 `amp/amp.img`

#### Scenario: 单刷 amp 分区

- **WHEN** 执行 `flange flash amp`
- **THEN** 仅 amp 分区被写入 `amp.img`，其余分区不动

#### Scenario: amp 关闭时刷写映射不含 amp

- **WHEN** amp 关闭并生成 `flash-config.json`
- **THEN** flash-config 不含 amp 分区条目（gate 生效）

### Requirement: validate_amp 校验 amp 配置自洽

`builder/config/validate.py` SHALL 新增 `validate_amp` 并挂入配置校验链：当 `config.amp.enabled` 为真时，SHALL 断言 `config.amp.mode ∈ {"hal", "rt-thread"}`、`partitions.entries` 含名为 `amp` 的非 raw 分区、且该 amp 分区 SHALL 排在 `grow_on_first_boot` 的 remaining rootfs **之前**（既有 `validate_rootfs_auto_grow` 禁止 remaining rootfs 之后出现任何非 raw 分区，amp 是非 raw 分区故必须前置）；任一不满足 SHALL 使配置校验失败并给出明确错误（仿 `validate_recovery_partition`）。

#### Scenario: 启用 amp 但缺 amp 分区

- **WHEN** `config.amp.enabled` 为真但 `partitions.entries` 无 amp 分区
- **THEN** 配置校验失败，错误指明缺少 amp 分区

#### Scenario: 非法 mode

- **WHEN** `config.amp.mode` 取 `"hal"`/`"rt-thread"` 之外的值
- **THEN** 配置校验失败，错误指明 mode 取值非法

#### Scenario: amp 分区排在 remaining rootfs 之后

- **WHEN** amp 分区被放在 `grow_on_first_boot` 的 remaining rootfs 之后
- **THEN** 配置校验失败（amp 非 raw 分区必须前置于 remaining rootfs）
