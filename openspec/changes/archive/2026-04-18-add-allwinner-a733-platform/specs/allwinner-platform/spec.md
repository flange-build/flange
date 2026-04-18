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

### Requirement: Allwinner 平台默认启用 adbd 调试通道
Allwinner 平台必须（SHALL）在 rootfs 中默认装配 `adbd` App，提供基于 USB gadget 的 adb 调试通道，使所有 Allwinner 板开箱具备与 Rockchip 平台对等的调试能力。

#### Scenario: 平台级 App 声明
- **WHEN** 读取 `platform/allwinner/config.py` 的 `rootfs.custom_packages` 字段
- **THEN** 列表包含字符串 `"adbd"`，使 `AppBuilder.build_all()` 在任意 Allwinner 板的构建中自动为其打包并安装 adbd.deb

#### Scenario: 板级未显式覆盖时的继承
- **WHEN** 某 Allwinner 板的 `board/<name>/config.py` 未声明 `rootfs.custom_packages`
- **THEN** 经三层配置合并后，该板的 `custom_packages` 至少包含 `"adbd"`（来自平台层），rootfs 构建产物内 `/usr/bin/adbd` 等文件存在

### Requirement: Allwinner 内核 USB gadget 保证
`AllwinnerKernelBuilder` 必须（SHALL）生成 `usb_gadget.config` fragment 并经 defconfig 合并确保 USB gadget 与 FunctionFS 为内建功能，覆盖 `radxa.config` 将 `USB_CONFIGFS` 降为模块的影响，使 `usbdevice.service` 在不依赖 modprobe 的前提下可用。

#### Scenario: override fragment 生成
- **WHEN** 执行 Allwinner 内核构建
- **THEN** `arch/arm64/configs/usb_gadget.config` 文件存在，内容至少包含：
  - `CONFIG_CONFIGFS_FS=y`
  - `CONFIG_USB_GADGET=y`
  - `CONFIG_USB_CONFIGFS=y`
  - `CONFIG_USB_CONFIGFS_F_FS=y`

#### Scenario: defconfig 合并顺序
- **WHEN** `platform/allwinner/a733/config.py` 的 `kernel.defconfig` 列表被 `configure()` 逐项应用
- **THEN** `usb_gadget.config` 在 `radxa.config` 和 `radxa_custom.config` 之后应用，最终 `.config` 中 `CONFIG_USB_CONFIGFS=y`（非 `=m`）

#### Scenario: 最终 `.config` 校验
- **WHEN** 内核构建完成，读取 `sources/repos/linux-a733/src/.config`
- **THEN** `CONFIG_USB_GADGET=y`、`CONFIG_USB_CONFIGFS=y`、`CONFIG_USB_CONFIGFS_F_FS=y`、`CONFIG_CONFIGFS_FS=y` 四项同时成立

### Requirement: A7Z 板级 USB gadget 配置
`board/radxa-cubie-a7z/overlay/etc/usbdevice.conf` 必须（SHALL）提供 A733 平台 USB gadget 的 VID/PID、gadget 组名、产品标识等参数，使 `usbdevice.service` 启动时能正确组装 configfs gadget 树。

#### Scenario: VID 使用 Allwinner 官方值
- **WHEN** 读取 A7Z rootfs 中 `/etc/usbdevice.conf`
- **THEN** `USB_VENDOR_ID=0x1f3a`（Allwinner Technology 注册 VID），使设备在宿主机 `lsusb` 中显示厂商为 "Allwinner Technology"

#### Scenario: USB_GROUP 与 Allwinner 命名空间一致
- **WHEN** `usbdevice start` 在 A7Z 上执行
- **THEN** configfs gadget 路径为 `/sys/kernel/config/usb_gadget/sunxi/`，与 Allwinner sunxi 生态命名对齐

#### Scenario: 默认启用 adb function
- **WHEN** A7Z 首次启动且无 `/etc/usbdevice.d/` 用户扩展
- **THEN** `USB_FUNCS=adb`，宿主机执行 `adb devices` 可识别到设备并进入 shell
