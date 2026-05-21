## MODIFIED Requirements

### Requirement: Device Tree Overlay 配置契约
平台、SoC、board 或 product 配置 MUST 通过 `boot.dtb_overlays` 声明需要从内核源码树（in-tree）构建并打包的 Device Tree Overlay 文件列表，MUST 通过 `boot.vendor_overlays` 声明需要从外部 vendor overlay 仓库构建并打包的 Device Tree Overlay 文件列表，MUST 通过 `boot.board_overlays` 声明需要从板私有源目录 `components/board/<board>/dtso/` 构建并打包的 Device Tree Overlay 文件列表，MUST 通过 `boot.default_overlays` 声明默认启动时需要应用的 overlay 文件列表。

此外，board 通过 `packages` 启用的硬件特性包中，`devicetree` 类型 component 编出的 `.dtbo` 构成第四源「package overlay」，由包机制注册进打包集合，与上述三源同等参与下列约束。package overlay 的源 `.dtso` 位于包目录的 `device-tree/` 子目录、由 device-tree-overlay 的同一 cpp+dtc 流水线编译。

`boot.default_overlays` MUST 保持声明顺序，并 MUST 是 `boot.dtb_overlays ∪ boot.vendor_overlays ∪ boot.board_overlays ∪ package overlays`（按 basename）的子集。

四源（`boot.dtb_overlays` / `boot.vendor_overlays` / `boot.board_overlays` / package overlays）之间，任意两源的 basename MUST NOT 重复——撞名时构建 MUST 失败，错误信息 MUST 列出冲突项与各自来源。

每个字段的每一项 MUST 是非空字符串，MUST 以 `.dtbo` 结尾，MUST NOT 包含 `/`，MUST NOT 以 `.` 起头。

#### Scenario: 同时声明三源 overlay
- **WHEN** 最终配置中 `boot.dtb_overlays == ["my-local.dtbo"]`、`boot.vendor_overlays == ["radxa-zero3-external-antenna.dtbo", "rk3568-i2c1.dtbo"]`、`boot.board_overlays == ["vim3l-spidev-spicc1.dtbo"]` 且 `boot.default_overlays == ["rk3568-i2c1.dtbo", "vim3l-spidev-spicc1.dtbo"]`
- **THEN** 构建系统将 `my-local.dtbo` 通过 in-tree 流程构建，将 `radxa-zero3-external-antenna.dtbo`、`rk3568-i2c1.dtbo` 通过 vendor overlay 仓库流程构建，将 `vim3l-spidev-spicc1.dtbo` 通过板私有源流程构建
- **AND** 四个 `.dtbo` 文件全部纳入打包集合
- **AND** extlinux 配置仅引用 `rk3568-i2c1.dtbo` 与 `vim3l-spidev-spicc1.dtbo`

#### Scenario: package overlay 纳入打包与默认应用
- **WHEN** board 通过 `packages` 启用的包提供 `rk3588-rock-5b-meizu-e3-panel.dtbo`（package overlay），且 `boot.default_overlays` 包含 `rk3588-rock-5b-meizu-e3-panel.dtbo`
- **THEN** 该 `.dtbo` 由 cpp+dtc 流水线编译并纳入打包集合
- **AND** extlinux 配置在 `fdtoverlays` 行引用该 overlay

#### Scenario: 默认 overlay 引用未打包文件
- **WHEN** `boot.default_overlays` 包含 `missing.dtbo` 但 `boot.dtb_overlays`、`boot.vendor_overlays`、`boot.board_overlays` 与 package overlays 的并集不包含 `missing.dtbo`
- **THEN** boot 组件构建失败
- **AND** 错误信息包含缺失的 overlay 文件名
- **AND** 错误信息列出四源各自的候选集合

#### Scenario: 任意两源 basename 撞名
- **WHEN** 四源（`boot.dtb_overlays` / `boot.vendor_overlays` / `boot.board_overlays` / package overlays）中任意两源同时包含 `foo.dtbo`
- **THEN** 构建失败
- **AND** 错误信息明确指出冲突的 basename `foo.dtbo` 同时来自哪两源

#### Scenario: 未声明 overlay 保持兼容
- **WHEN** `boot.dtb_overlays`、`boot.vendor_overlays`、`boot.board_overlays`、`boot.default_overlays` 均为空或未声明，且 board 未通过 `packages` 启用任何 `devicetree` component
- **THEN** kernel、device-tree-overlay、boot 与 image 组件保持现有无 overlay 的构建行为
- **AND** extlinux 配置不生成 `fdtoverlays` 行
