## MODIFIED Requirements

### Requirement: Allwinner 内核构建支持 BSP 集成
`AllwinnerKernelBuilder` 必须（SHALL）在编译前将 BSP 仓库集成到内核源码树的 `bsp/` 目录，并将 device 仓库中的 board DTS 复制到内核 DTS 目录。BSP 和 device 目录通过命名仓库 `linux-a733` 的子路径获取（`bsp/` 和 `device-a733/`），与 kernel 共用同一次 clone。

#### Scenario: BSP 目录集成
- **WHEN** 执行 Allwinner 内核构建，`repos.linux-a733` 已声明
- **THEN** 内核源码树中的 `bsp/` 为 `sources/repos/linux-a733/bsp/` 的 symlink 或副本

#### Scenario: kernel/BSP/device 版本一致
- **WHEN** linux-a733 聚合仓库的 `.gitmodules` 声明特定 commit
- **THEN** kernel、BSP、device 三者版本组合由聚合仓库统一管理，不会出现版本漂移

#### Scenario: DTS 文件准备
- **WHEN** config 指定 `kernel_device.board_dts_path` 为 `"configs/cubie_a7z/linux-5.15/board.dts"` 且 `kernel.dts` 为 `"sun60i-a733-cubie-a7z"`
- **THEN** board.dts 从 `sources/repos/linux-a733/device-a733/configs/cubie_a7z/linux-5.15/board.dts` 复制到 `arch/arm64/boot/dts/allwinner/sun60i-a733-cubie-a7z.dts`

#### Scenario: BSP DTSI 链接
- **WHEN** BSP 目录的 `configs/linux-5.15/` 包含 DTSI 文件
- **THEN** 这些 DTSI 文件链接到 `arch/arm64/boot/dts/allwinner/` 目录

## ADDED Requirements

### Requirement: Allwinner 直接使用 linux-a733 原始 patches
`AllwinnerKernelBuilder` 必须（SHALL）直接应用 `sources/repos/linux-a733/debian/patches/` 中的原始补丁，不再维护手动适配 `src/` 前缀的自定义版本。

#### Scenario: patches 从聚合仓库应用
- **WHEN** 执行 Allwinner 内核构建
- **THEN** 按 `sources/repos/linux-a733/debian/patches/series` 声明的顺序应用补丁

#### Scenario: patch 应用目录是聚合仓库根
- **WHEN** 应用含 `a/src/...` 和 `a/bsp/...` 路径的补丁
- **THEN** patch 在 `sources/repos/linux-a733/` 根目录应用，路径前缀自然匹配（无需 -p2 或路径改写）

#### Scenario: patches 顺序由 series 文件决定
- **WHEN** `debian/patches/series` 列出 4 个补丁
- **THEN** 按 series 文件声明顺序应用，任一失败则构建失败

### Requirement: Allwinner bootloader 复用 u-boot-aw2501 命名仓库
`AllwinnerBootloaderBuilder` 必须（SHALL）通过 `from_repo: "u-boot-aw2501"` 引用命名仓库获取源码，不再使用组件级独立 `repo` 配置。

#### Scenario: bootloader 从命名仓库构建
- **WHEN** 执行 Allwinner bootloader 构建
- **THEN** 源码目录为 `sources/repos/u-boot-aw2501/`（含所有子模块）
