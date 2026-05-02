## MODIFIED Requirements

### Requirement: Device Tree Overlay 配置契约
平台、SoC、board 或 product 配置 MUST 通过 `boot.dtb_overlays` 声明需要从内核源码树（in-tree）构建并打包的 Device Tree Overlay 文件列表，MUST 通过 `boot.vendor_overlays` 声明需要从外部 vendor overlay 仓库构建并打包的 Device Tree Overlay 文件列表，MUST 通过 `boot.default_overlays` 声明默认启动时需要应用的 overlay 文件列表。

`boot.default_overlays` MUST 保持声明顺序，并 MUST 是 `boot.dtb_overlays ∪ boot.vendor_overlays`（按 basename）的子集。

`boot.dtb_overlays` 与 `boot.vendor_overlays` 的 basename MUST NOT 重复——撞名时构建 MUST 失败，错误信息 MUST 列出冲突项与各自来源。

每个字段的每一项 MUST 是非空字符串，MUST 以 `.dtbo` 结尾，MUST NOT 包含 `/`，MUST NOT 以 `.` 起头。

#### Scenario: 同时声明两源 overlay
- **WHEN** 最终配置中 `boot.dtb_overlays == ["my-local.dtbo"]`、`boot.vendor_overlays == ["radxa-zero3-external-antenna.dtbo", "rk3568-i2c1.dtbo"]` 且 `boot.default_overlays == ["rk3568-i2c1.dtbo"]`
- **THEN** 构建系统将 `my-local.dtbo` 通过 in-tree 流程构建，将 `radxa-zero3-external-antenna.dtbo`、`rk3568-i2c1.dtbo` 通过 vendor overlay 仓库流程构建
- **AND** 三个 `.dtbo` 文件全部纳入打包集合
- **AND** extlinux 配置仅引用 `rk3568-i2c1.dtbo`

#### Scenario: 默认 overlay 引用未打包文件
- **WHEN** `boot.default_overlays` 包含 `missing.dtbo` 但 `boot.dtb_overlays` 与 `boot.vendor_overlays` 的并集不包含 `missing.dtbo`
- **THEN** boot 组件构建失败
- **AND** 错误信息包含缺失的 overlay 文件名
- **AND** 错误信息列出 `boot.dtb_overlays` 与 `boot.vendor_overlays` 各自的候选集合

#### Scenario: 两源 basename 撞名
- **WHEN** `boot.dtb_overlays` 与 `boot.vendor_overlays` 同时包含 `foo.dtbo`
- **THEN** 构建失败
- **AND** 错误信息明确指出冲突的 basename `foo.dtbo` 同时来自两源

#### Scenario: 未声明 overlay 保持兼容
- **WHEN** `boot.dtb_overlays`、`boot.vendor_overlays` 与 `boot.default_overlays` 均为空或未声明
- **THEN** kernel、device-tree-overlay、boot 与 image 组件保持现有无 overlay 的构建行为
- **AND** extlinux 配置不生成 `fdtoverlays` 行

### Requirement: boot 分区 overlay 文件布局
boot builder MUST 将 `target/kernel/overlay/` 中被 `boot.dtb_overlays` 声明的 `.dtbo` 文件，以及 `target/dt-overlays/` 中被 `boot.vendor_overlays` 声明的 `.dtbo` 文件，复制到平台约定的 boot 分区 overlay 目录。

base DTB MUST 放在 `/dtbs/<vendor>/`，所有 overlay（无论来自哪一源）MUST 平铺在 `/dtbs/<vendor>/overlay/`，文件名即 basename。

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

#### Scenario: dst 撞名报错
- **WHEN** 在 `target/kernel/overlay/` 与 `target/dt-overlays/` 都存在 `foo.dtbo`，且配置同时声明（违反唯一性）
- **THEN** 复制阶段 raise 异常
- **AND** 异常信息包含已存在路径与本次源路径，可定位冲突来源

## ADDED Requirements

### Requirement: vendor overlay 仓库构建
flange MUST 提供独立组件 `device-tree-overlay`，从外部 vendor overlay 仓库（git pin 到固定 ref）按 `boot.vendor_overlays` 列表编译 `.dtbo` 产物到 `target/dt-overlays/`。

该组件 MUST vendor 无关，从 `config["platform"]["vendor"]` 读取 vendor 名（如 `rockchip`、`allwinner`），用于在仓库中定位子目录 `arch/arm64/boot/dts/<vendor>/overlays/<stem>.dts`。`platform.vendor` 字段缺失或值在仓库中无对应子目录时，MUST 报错并明确指出问题。

编译流程 MUST 等价于：

```bash
cpp -nostdinc -undef -x assembler-with-cpp -E \
    -I {kernel_src_dir}/include \
    -I {radxa_src_dir}/arch/arm64/boot/dts/{vendor}/overlays \
    {dts} -o {tmp}
dtc -@ -I dts -O dtb -o {dtbo} {tmp}
```

其中 `kernel_src_dir` 取自 kernel 组件的源码目录，`radxa_src_dir` 取自 device-tree-overlay 组件的源码目录。

`boot.vendor_overlays` 中声明的 stem 在仓库对应 vendor 子目录下不存在时 MUST 报错，错误信息 MUST 列出该 vendor 下若干可用 stem 与总数。

#### Scenario: 编译声明的 vendor overlay
- **WHEN** `boot.vendor_overlays == ["radxa-zero3-external-antenna.dtbo"]` 且 `config["platform"]["vendor"] == "rockchip"`，仓库中存在 `arch/arm64/boot/dts/rockchip/overlays/radxa-zero3-external-antenna.dts`
- **THEN** device-tree-overlay 组件成功编译并生成 `target/dt-overlays/radxa-zero3-external-antenna.dtbo`

#### Scenario: 仓库中找不到声明的 stem
- **WHEN** `boot.vendor_overlays == ["nonexistent-overlay.dtbo"]` 且仓库对应 vendor 子目录中不存在 `nonexistent-overlay.dts`
- **THEN** device-tree-overlay 组件构建失败
- **AND** 错误信息包含 `nonexistent-overlay`
- **AND** 错误信息列出该 vendor 下若干可用 stem 名与总数

#### Scenario: 缺失 platform.vendor
- **WHEN** `boot.vendor_overlays` 非空但 `config["platform"]` 中无 `vendor` 字段
- **THEN** device-tree-overlay 组件构建失败
- **AND** 错误信息明确指出 `platform.vendor` 字段需补充

#### Scenario: 空 vendor_overlays short-circuit
- **WHEN** `boot.vendor_overlays == []`
- **THEN** device-tree-overlay 组件 source 阶段仍执行（保持内容哈希稳定）
- **AND** compile 阶段不执行任何 cpp / dtc 调用
- **AND** `target/dt-overlays/` 为空目录或不创建

### Requirement: vendor overlay 仓库 source pin
device-tree-overlay 组件的 source 声明 MUST pin 到外部 vendor overlay 仓库的固定 git ref（推荐 release tag）。flange 内容哈希 MUST 包含该 ref，使 ref 升级时整个组件链触发增量重 build。

#### Scenario: ref 变更触发重建
- **WHEN** `components/device-tree-overlay/source.py` 中的 git ref 从 `tagA` 改为 `tagB`
- **AND** 其他配置不变
- **THEN** device-tree-overlay 组件被识别为内容变化
- **AND** 触发该组件及下游 boot 组件的重建
