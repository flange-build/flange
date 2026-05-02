## MODIFIED Requirements

### Requirement: A733 内核编译产物
`AllwinnerA733KernelBuilder` 的 `collect()` 必须（SHALL）返回 Image、DTB 和 modules 三项基础产物；当 `boot.dtb_overlays` 非空时，还必须（SHALL）返回 `dtbos` 目录，目录中包含所有声明的 `.dtbo` overlay 产物。

#### Scenario: 基础产物收集
- **WHEN** 内核编译成功完成且未声明 `boot.dtb_overlays`
- **THEN** collect 返回字典包含 `"image"` (Image 路径)、`"dtb"` (DTB 路径)、`"modules"` (modules staging 目录路径)

#### Scenario: overlay 产物收集
- **WHEN** 内核编译成功完成且 config 声明 `boot.dtb_overlays == ["i2c1.dtbo", "spi1.dtbo"]`
- **THEN** collect 返回字典包含 `"dtbos"` 目录路径
- **AND** 该目录包含 `i2c1.dtbo`
- **AND** 该目录包含 `spi1.dtbo`

### Requirement: A733 Boot 分区组装
`AllwinnerA733BootBuilder` 必须（SHALL）将 Image、DTB 和 extlinux.conf 组装到 boot.img 中，文件布局遵循统一 extlinux + dtbs 规范。当 `boot.dtb_overlays` 非空时，boot.img 必须（SHALL）包含 `/dtbs/allwinner/overlay/*.dtbo`；当 `boot.default_overlays` 非空时，extlinux.conf 与 recovery.conf 必须（SHALL）通过 `fdtoverlays` 引用这些默认 overlay。

#### Scenario: boot 分区文件布局
- **WHEN** 构建 `allwinnera733` 平台的 boot.img
- **THEN** boot.img 内包含 `/extlinux/Image`、`/dtbs/allwinner/sunxi.dtb`（或 config 指定的 DTB 文件名）、`/extlinux/extlinux.conf`
- **AND** recovery 启用时包含 `/extlinux/recovery.conf`

#### Scenario: boot 分区 overlay 文件布局
- **WHEN** 构建 `allwinnera733` 平台的 boot.img 且 `target/kernel/overlay/i2c1.dtbo` 存在
- **THEN** boot.img 内包含 `/dtbs/allwinner/overlay/i2c1.dtbo`

#### Scenario: extlinux.conf 内容
- **WHEN** config 指定 `boot.kernel_args` 和 `boot.dtb_filename`
- **THEN** 生成的 extlinux.conf 包含正确的 kernel、devicetree、append 行，root 指向 rootfs 分区

#### Scenario: extlinux.conf 包含默认 overlay
- **WHEN** config 指定 `boot.default_overlays == ["i2c1.dtbo", "spi1.dtbo"]`
- **THEN** 生成的 extlinux.conf 包含 `fdtoverlays /dtbs/allwinner/overlay/i2c1.dtbo /dtbs/allwinner/overlay/spi1.dtbo`

#### Scenario: recovery.conf 包含默认 overlay
- **WHEN** recovery 启用且 config 指定 `boot.default_overlays == ["i2c1.dtbo"]`
- **THEN** 生成的 recovery.conf 包含 `fdtoverlays /dtbs/allwinner/overlay/i2c1.dtbo`
