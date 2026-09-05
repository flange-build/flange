## MODIFIED Requirements

### Requirement: A733 内核构建支持 BSP 集成
`AllwinnerA733KernelBuilder` 必须（SHALL）在编译前将 BSP 仓库集成到内核源码树的 `bsp/` 目录，并将 device 仓库中的 board DTS 复制到内核 DTS 目录。BSP 和 device 目录通过命名仓库 `linux-a733` 的子路径获取（`bsp/` 和 `device-a733/`），与 kernel 共用同一次 clone。

#### Scenario: BSP 目录集成
- **WHEN** 执行 `allwinnera733` 平台的内核构建，`sources.linux-a733` 已声明
- **THEN** 内核源码树中的 `bsp/` 为 `<build_root>/work/<target.key>/sources/<linux-a733-worktree-id>/bsp/` 的 symlink 或副本

#### Scenario: kernel/BSP/device 版本一致
- **WHEN** linux-a733 聚合仓库的 `.gitmodules` 声明特定 commit
- **THEN** kernel、BSP、device 三者版本组合由聚合仓库统一管理，不会出现版本漂移

#### Scenario: DTS 文件准备
- **WHEN** config 指定 `kernel_device.board_dts_path` 为 `"configs/cubie_a7z/linux-5.15/board.dts"` 且 `kernel.device_tree.name` 为 `"sun60i-a733-cubie-a7z"`
- **THEN** board.dts 从 `<build_root>/work/<target.key>/sources/<linux-a733-worktree-id>/device-a733/configs/cubie_a7z/linux-5.15/board.dts` 复制到 `arch/arm64/boot/dts/allwinner/sun60i-a733-cubie-a7z.dts`（内核上游 DTS 目录名保持 `allwinner`，不随 flange 平台重命名而变化）

#### Scenario: BSP DTSI 链接
- **WHEN** BSP 目录的 `configs/linux-5.15/` 包含 DTSI 文件
- **THEN** 这些 DTSI 文件链接到 `arch/arm64/boot/dts/allwinner/` 目录

### Requirement: A733 Bootloader 源码构建模式
`AllwinnerA733BootloaderBuilder` 必须（SHALL）从命名仓库 `u-boot-aw2501` 获取源码，
在构建前应用平台级与板级 bootloader patches，然后编译目标板产物。

#### Scenario: 源码构建
- **WHEN** 执行 `allwinnera733` 平台的 bootloader 构建
- **THEN** 构建器从 `<build_root>/work/<target.key>/sources/<u-boot-aw2501-worktree-id>/` 获取源码并执行目标板 `make`
- **AND** 收集 `boot0_sdcard.bin`、`boot0_ufs.bin`、`boot_package.fex` 等产物

#### Scenario: bootloader patches
- **WHEN** 执行 `allwinnera733` 平台的 bootloader 构建
- **THEN** 在编译前应用 `components/platform/allwinnera733/patches/bootloader/*.patch`
- **AND** 应用 `components/board/<board>/patches/bootloader/*.patch`

### Requirement: A733 内核 USB gadget 保证
`AllwinnerA733KernelBuilder` 必须（SHALL）生成 `usb_gadget.config` fragment 并经 defconfig 合并确保 USB gadget 与 FunctionFS 为内建功能，覆盖 `radxa.config` 将 `USB_CONFIGFS` 降为模块的影响，使 `usbdevice.service` 在不依赖 modprobe 的前提下可用。

#### Scenario: override fragment 生成
- **WHEN** 执行 `allwinnera733` 平台的内核构建
- **THEN** `arch/arm64/configs/usb_gadget.config` 文件存在，内容至少包含：
  - `CONFIG_CONFIGFS_FS=y`
  - `CONFIG_USB_GADGET=y`
  - `CONFIG_USB_CONFIGFS=y`
  - `CONFIG_USB_CONFIGFS_F_FS=y`

#### Scenario: defconfig 合并顺序
- **WHEN** `components/platform/allwinnera733/a733/config.jsonnet` 的 `kernel.defconfig` 列表被 `configure()` 逐项应用
- **THEN** `usb_gadget.config` 在 `radxa.config` 和 `radxa_custom.config` 之后应用，最终 `.config` 中 `CONFIG_USB_CONFIGFS=y`（非 `=m`）

#### Scenario: 最终 `.config` 校验
- **WHEN** 内核构建完成，读取 `<build_root>/work/<target.key>/sources/<linux-a733-worktree-id>/src/.config`
- **THEN** `CONFIG_USB_GADGET=y`、`CONFIG_USB_CONFIGFS=y`、`CONFIG_USB_CONFIGFS_F_FS=y`、`CONFIG_CONFIGFS_FS=y` 四项同时成立

### Requirement: A733 直接使用 linux-a733 原始 patches
`AllwinnerA733KernelBuilder` 必须（SHALL）直接应用 `<build_root>/work/<target.key>/sources/<linux-a733-worktree-id>/debian/patches/` 中的原始补丁，不再维护手动适配 `src/` 前缀的自定义版本。

#### Scenario: patches 从聚合仓库应用
- **WHEN** 执行 `allwinnera733` 平台的内核构建
- **THEN** 按 `<build_root>/work/<target.key>/sources/<linux-a733-worktree-id>/debian/patches/series` 声明的顺序应用补丁

#### Scenario: patch 应用目录是聚合仓库根
- **WHEN** 应用含 `a/src/...` 和 `a/bsp/...` 路径的补丁
- **THEN** patch 在 `<build_root>/work/<target.key>/sources/<linux-a733-worktree-id>/` 根目录应用，路径前缀自然匹配（无需 -p2 或路径改写）

#### Scenario: patches 顺序由 series 文件决定
- **WHEN** `debian/patches/series` 列出 4 个补丁
- **THEN** 按 series 文件声明顺序应用，任一失败则构建失败

### Requirement: A733 bootloader 复用 u-boot-aw2501 命名仓库
`AllwinnerA733BootloaderBuilder` 必须（SHALL）通过 `source: {name: "u-boot-aw2501"}` 引用顶层 canonical source 获取源码。

#### Scenario: bootloader 从命名仓库构建
- **WHEN** 执行 `allwinnera733` 平台的 bootloader 构建
- **THEN** 源码目录为 `<build_root>/work/<target.key>/sources/<u-boot-aw2501-worktree-id>/`（含所有子模块）

### Requirement: A733 AIC8800 USB 内核模块配置
`AllwinnerA733KernelBuilder` 必须（SHALL）支持生成并合并 AIC8800 USB Wi-Fi 的 kernel config fragment，
覆盖上游 `radxa.config` 中关闭 AIC WLAN 的设置，使 AIC8800 USB 驱动以 kernel module（内核模块）方式编译。

#### Scenario: AIC8800 fragment 生成
- **WHEN** 执行 `allwinnera733` 平台的内核构建
- **THEN** `arch/arm64/configs/aic8800_wlan.config` 文件存在
- **AND** 内容至少包含 `CONFIG_AIC_WLAN_SUPPORT=y`
- **AND** 内容至少包含 `CONFIG_AIC8800_USB=y`
- **AND** 内容至少包含 `CONFIG_AIC_LOADFW_SUPPORT=m`
- **AND** 内容至少包含 `CONFIG_AIC8800_WLAN_SUPPORT=m`
- **AND** 内容至少包含 `# CONFIG_AIC8800_SDIO is not set`

#### Scenario: AIC8800 fragment 合并顺序
- **WHEN** `components/platform/allwinnera733/a733/config.jsonnet` 的 `kernel.defconfig` 列表被 `configure()` 逐项应用
- **THEN** `aic8800_wlan.config` 在 `radxa.config` 和 `radxa_custom.config` 之后应用
- **AND** `aic8800_wlan.config` 在 `case_insensitive_fix.config` 之前应用

#### Scenario: 最终内核配置启用 USB 模式
- **WHEN** 内核构建完成，读取 `<build_root>/work/<target.key>/sources/<linux-a733-worktree-id>/src/.config`
- **THEN** `CONFIG_AIC_WLAN_SUPPORT=y`
- **AND** `CONFIG_AIC8800_USB=y`
- **AND** `CONFIG_AIC8800_SDIO` 未启用
- **AND** `CONFIG_AIC_LOADFW_SUPPORT=m`
- **AND** `CONFIG_AIC8800_WLAN_SUPPORT=m`
