## MODIFIED Requirements

### Requirement: Device Tree Overlay 配置契约
平台、SoC、board 或 product 配置 MUST 通过 `boot.dtb_overlays` 声明需要从内核源码树（in-tree）构建并打包的 Device Tree Overlay 文件列表，MUST 通过 `boot.vendor_overlays` 声明需要从外部 vendor overlay 仓库构建并打包的 Device Tree Overlay 文件列表，MUST 通过 `boot.board_overlays` 声明需要从板私有源目录 `components/board/<board>/dtso/` 构建并打包的 Device Tree Overlay 文件列表，MUST 通过 `boot.default_overlays` 声明默认启动时需要应用的 overlay 文件列表。

`boot.default_overlays` MUST 保持声明顺序，并 MUST 是 `boot.dtb_overlays ∪ boot.vendor_overlays ∪ boot.board_overlays`（按 basename）的子集。

三源（`boot.dtb_overlays` / `boot.vendor_overlays` / `boot.board_overlays`）之间，任意两源的 basename MUST NOT 重复——撞名时构建 MUST 失败，错误信息 MUST 列出冲突项与各自来源。

每个字段的每一项 MUST 是非空字符串，MUST 以 `.dtbo` 结尾，MUST NOT 包含 `/`，MUST NOT 以 `.` 起头。

#### Scenario: 同时声明三源 overlay
- **WHEN** 最终配置中 `boot.dtb_overlays == ["my-local.dtbo"]`、`boot.vendor_overlays == ["radxa-zero3-external-antenna.dtbo", "rk3568-i2c1.dtbo"]`、`boot.board_overlays == ["vim3l-spidev-spicc1.dtbo"]` 且 `boot.default_overlays == ["rk3568-i2c1.dtbo", "vim3l-spidev-spicc1.dtbo"]`
- **THEN** 构建系统将 `my-local.dtbo` 通过 in-tree 流程构建，将 `radxa-zero3-external-antenna.dtbo`、`rk3568-i2c1.dtbo` 通过 vendor overlay 仓库流程构建，将 `vim3l-spidev-spicc1.dtbo` 通过板私有源流程构建
- **AND** 四个 `.dtbo` 文件全部纳入打包集合
- **AND** extlinux 配置仅引用 `rk3568-i2c1.dtbo` 与 `vim3l-spidev-spicc1.dtbo`

#### Scenario: 默认 overlay 引用未打包文件
- **WHEN** `boot.default_overlays` 包含 `missing.dtbo` 但 `boot.dtb_overlays`、`boot.vendor_overlays` 与 `boot.board_overlays` 的并集不包含 `missing.dtbo`
- **THEN** boot 组件构建失败
- **AND** 错误信息包含缺失的 overlay 文件名
- **AND** 错误信息列出 `boot.dtb_overlays`、`boot.vendor_overlays` 与 `boot.board_overlays` 各自的候选集合

#### Scenario: 任意两源 basename 撞名
- **WHEN** `boot.dtb_overlays` 与 `boot.vendor_overlays` 同时包含 `foo.dtbo`，或 `boot.dtb_overlays` 与 `boot.board_overlays` 同时包含 `foo.dtbo`，或 `boot.vendor_overlays` 与 `boot.board_overlays` 同时包含 `foo.dtbo`
- **THEN** 构建失败
- **AND** 错误信息明确指出冲突的 basename `foo.dtbo` 同时来自哪两源

#### Scenario: 未声明 overlay 保持兼容
- **WHEN** `boot.dtb_overlays`、`boot.vendor_overlays`、`boot.board_overlays` 与 `boot.default_overlays` 均为空或未声明
- **THEN** kernel、device-tree-overlay、boot 与 image 组件保持现有无 overlay 的构建行为
- **AND** extlinux 配置不生成 `fdtoverlays` 行

### Requirement: boot 分区 overlay 文件布局
boot builder MUST 将 `target/kernel/overlay/` 中被 `boot.dtb_overlays` 声明的 `.dtbo` 文件、device-tree-overlay 组件产物中被 `boot.vendor_overlays` 声明的 `.dtbo` 文件、以及 device-tree-overlay 组件产物中被 `boot.board_overlays` 声明的 `.dtbo` 文件，复制到平台约定的 boot 分区 overlay 目录。

base DTB MUST 放在 `/dtbs/<vendor>/`，所有 overlay（无论来自三源中哪一源）MUST 平铺在 `/dtbs/<vendor>/overlay/`，文件名即 basename。

复制阶段若发现 dst 中已存在同名 `.dtbo` 文件 → MUST raise 异常并终止构建。

生成 extlinux 前 MUST 校验 `boot.default_overlays` 引用的文件已存在于 staging 目录。

#### Scenario: Rockchip boot 分区两源平铺
- **WHEN** Rockchip boot 组件构建，`boot.dtb_overlays == ["my-local.dtbo"]` 且 `boot.vendor_overlays == ["rk3568-i2c1.dtbo"]`
- **THEN** boot.img staging 中包含 `/dtbs/rockchip/overlay/my-local.dtbo`
- **AND** boot.img staging 中包含 `/dtbs/rockchip/overlay/rk3568-i2c1.dtbo`

#### Scenario: Allwinner A733 boot 分区两源平铺
- **WHEN** Allwinner A733 boot 组件构建，`boot.dtb_overlays == ["my-local.dtbo"]` 且 `boot.vendor_overlays == ["a733-foo.dtbo"]`
- **THEN** boot.img staging 中包含 `/dtbs/allwinner/overlay/my-local.dtbo`
- **AND** boot.img staging 中包含 `/dtbs/allwinner/overlay/a733-foo.dtbo`

#### Scenario: Amlogic boot 分区含 board 私有 overlay
- **WHEN** Amlogic（khadas-vim3l）boot 组件构建，`boot.board_overlays == ["vim3l-spidev-spicc1.dtbo"]`
- **THEN** boot.img staging 中包含 `/dtbs/amlogic/overlay/vim3l-spidev-spicc1.dtbo`

#### Scenario: dst 撞名报错
- **WHEN** 三源中任意两源同时声明 `foo.dtbo`，复制时 dst 中已存在
- **THEN** 复制阶段 raise 异常
- **AND** 异常信息包含已存在路径与本次源路径，可定位冲突来源

## ADDED Requirements

### Requirement: 板私有 overlay 源目录与编译
flange MUST 支持从 `components/board/<board>/dtso/` 目录读取板私有 overlay 源文件（`.dts` 或 `.dtso` 后缀），由 `device-tree-overlay` 组件按 `boot.board_overlays` 列表编译产生 `.dtbo`。

板私有 overlay 编译流程 MUST 与 vendor overlay 复用同一 `cpp + dtc` 流水线，等价于：

```bash
cpp -nostdinc -undef -x assembler-with-cpp -E \
    -I {kernel_src_dir}/include \
    -I components/board/<board>/dtso \
    {dts_or_dtso} -o {tmp}
dtc -@ -I dts -O dtb -o {dtbo} {tmp}
```

其中 `kernel_src_dir` 取自 kernel 组件的源码目录。产物 MUST 与 vendor overlay 落到同一 target 子目录（`target/device-tree-overlay/overlays/`），由 boot 组件统一收集。

`boot.board_overlays` 中声明的 stem 在 `components/board/<board>/dtso/` 下不存在（`.dts` / `.dtso` 都没有）时 MUST 报错，错误信息 MUST 列出该目录下若干可用 stem 与总数。

`boot.board_overlays` 非空但 `config["board"]` 字段缺失时 MUST 报错（不应正常发生）。

#### Scenario: 编译板私有 overlay
- **WHEN** `boot.board_overlays == ["vim3l-spidev-spicc1.dtbo"]` 且 `config["board"] == "khadas-vim3l"`，仓库中存在 `components/board/khadas-vim3l/dtso/vim3l-spidev-spicc1.dtso`
- **THEN** device-tree-overlay 组件成功编译并把 `vim3l-spidev-spicc1.dtbo` 收集到 `target/device-tree-overlay/overlays/`

#### Scenario: 板私有源目录找不到声明的 stem
- **WHEN** `boot.board_overlays == ["nonexistent-overlay.dtbo"]` 且 `components/board/<board>/dtso/` 中既无 `nonexistent-overlay.dts` 也无 `nonexistent-overlay.dtso`
- **THEN** device-tree-overlay 组件构建失败
- **AND** 错误信息包含 `nonexistent-overlay`
- **AND** 错误信息列出该 board 私有 dtso 目录下若干可用 stem 名

#### Scenario: 板私有源目录不存在
- **WHEN** `boot.board_overlays` 非空但 `components/board/<board>/dtso/` 目录不存在
- **THEN** device-tree-overlay 组件构建失败
- **AND** 错误信息明确指出缺失目录路径与建议（"请创建该目录并放入对应 .dts/.dtso 文件"）

#### Scenario: 空 board_overlays 与空 vendor_overlays 同时存在
- **WHEN** `boot.vendor_overlays == []` 且 `boot.board_overlays == []`
- **THEN** device-tree-overlay 组件 source 阶段仍执行（保持内容哈希稳定）
- **AND** compile 阶段不执行任何 cpp / dtc 调用
- **AND** 该组件 target 子目录为空
