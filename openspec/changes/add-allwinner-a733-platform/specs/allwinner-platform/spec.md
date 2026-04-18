## ADDED Requirements

### Requirement: Allwinner 内核构建支持 BSP 集成
`AllwinnerKernelBuilder` 必须（SHALL）在编译前将 BSP 仓库集成到内核源码树的 `bsp/` 目录，并将 device 仓库中的 board DTS 复制到内核 DTS 目录。

#### Scenario: BSP 目录集成
- **WHEN** 执行 Allwinner 内核构建
- **THEN** 内核源码树中的 `bsp/` 为 BSP 仓库的 symlink 或副本，且内核 Makefile 可通过 `drivers-y += bsp/` 编译 BSP 驱动

#### Scenario: DTS 文件准备
- **WHEN** config 指定 `kernel_device.board_dts_path` 为 `"configs/cubie_a7z/linux-5.15/board.dts"` 且 `kernel.dts` 为 `"sun60i-a733-cubie-a7z"`
- **THEN** board.dts 被复制到 `arch/arm64/boot/dts/allwinner/sun60i-a733-cubie-a7z.dts`

#### Scenario: BSP DTSI 链接
- **WHEN** BSP 仓库的 `configs/linux-5.15/` 目录包含 `sun60iw2p1.dtsi` 等 DTSI 文件
- **THEN** 这些 DTSI 文件被链接到 `arch/arm64/boot/dts/allwinner/` 目录，使 board.dts 的 `#include` 指令能正确解析

### Requirement: Allwinner 内核多步 Defconfig 合并
`AllwinnerKernelBuilder` 必须（SHALL）支持多步 defconfig 合并。当 `kernel.defconfig` 为列表时，按顺序执行每个 defconfig target。

#### Scenario: 两步 defconfig
- **WHEN** config 中 `kernel.defconfig` 为 `["defconfig", "radxa.config"]`
- **THEN** 构建器依次执行 `make defconfig` 和 `make radxa.config`，最终 `.config` 包含两者合并的结果

### Requirement: Allwinner 内核编译产物
`AllwinnerKernelBuilder` 的 `collect()` 必须（SHALL）返回 Image、DTB 和 modules 三项产物。

#### Scenario: 产物收集
- **WHEN** 内核编译成功完成
- **THEN** collect 返回字典包含 `"image"` (Image 路径)、`"dtb"` (DTB 路径)、`"modules"` (modules staging 目录路径)

### Requirement: Allwinner Bootloader 预编译固件模式
`AllwinnerBootloaderBuilder` 必须（SHALL）从固件仓库拉取预编译的 bootloader 二进制，不执行编译。

#### Scenario: 固件拉取
- **WHEN** 执行 Allwinner bootloader 构建
- **THEN** 构建器从 config 中指定的固件仓库克隆/更新源码，并收集 `boot0_sdcard.bin`、`boot0_ufs.bin`、`boot_package.fex` 三项产物

#### Scenario: 无编译步骤
- **WHEN** 执行 Allwinner bootloader 构建
- **THEN** 不调用 `make`，不需要交叉编译工具链

### Requirement: Allwinner Boot 分区组装
`AllwinnerBootBuilder` 必须（SHALL）将 Image、DTB 和 extlinux.conf 组装到 boot.img 中，文件布局遵循 Allwinner extlinux 规范。

#### Scenario: boot 分区文件布局
- **WHEN** 构建 Allwinner boot.img
- **THEN** boot.img 内包含 `/extlinux/Image`、`/extlinux/sunxi.dtb`（或 config 指定的 DTB 文件名）、`/extlinux/extlinux.conf`

#### Scenario: extlinux.conf 内容
- **WHEN** config 指定 `boot.kernel_args` 和 `boot.dtb_filename`
- **THEN** 生成的 extlinux.conf 包含正确的 kernel、devicetree、append 行，root 指向 rootfs 分区

### Requirement: Allwinner Rootfs 构建
`AllwinnerRootfsBuilder` 必须（SHALL）复用 `RootfsBuilder` 基类的通用能力（overlay、firmware、两阶段缓存），生成 ext4 rootfs.img。

#### Scenario: rootfs 构建流程
- **WHEN** 执行 Allwinner rootfs 构建
- **THEN** 完成 Phase 1 (base tarball + apt install) 和 Phase 2 (custom deb + overlay + firmware + 密码设置)，输出 ext4 rootfs.img

### Requirement: Allwinner 整盘镜像组装
`AllwinnerImageBuilder` 必须（SHALL）将 bootloader 固件和分区镜像按 SD 卡分区表布局组装成 raw.img。

#### Scenario: SD 卡镜像组装
- **WHEN** 执行 Allwinner image 构建
- **THEN** raw.img 中 boot0_sdcard.bin 写入 sector 256，boot_package.fex 写入 sector 24576，boot.img 和 rootfs.img 写入对应分区 offset

#### Scenario: GPT 分区表
- **WHEN** raw.img 生成完成
- **THEN** 非 raw 类型分区在 GPT 分区表中有对应条目

### Requirement: Allwinner 平台配置三层继承
Allwinner 平台必须（SHALL）遵循 flange 的三层配置继承体系：platform → SoC → board。

#### Scenario: 配置合并
- **WHEN** lunch target 为 `radxa-cubie-a7z-default-debug`
- **THEN** 最终配置为 `platform/allwinner/config.py` → `platform/allwinner/a733/config.py` → `board/radxa-cubie-a7z/config.py` 三层深度合并的结果
