# allwinnera733-platform Specification

## Purpose
Allwinner A733 SoC 家族（sun60iw2p1）的平台级构建策略，覆盖 kernel / bootloader / rootfs / boot / image 全套 ComponentBuilder 以及 PLATFORM + SOC 两层配置继承。作为 flange 内 `platform = "allwinnera733"` 的权威规范；由 change `rename-allwinner-to-allwinnera733` 从原 `allwinner-platform` capability 整体迁移而来。
## Requirements
### Requirement: A733 内核构建支持 BSP 集成
`AllwinnerA733KernelBuilder` 必须（SHALL）在编译前将 BSP 仓库集成到内核源码树的 `bsp/` 目录，并将 device 仓库中的 board DTS 复制到内核 DTS 目录。BSP 和 device 目录通过命名仓库 `linux-a733` 的子路径获取（`bsp/` 和 `device-a733/`），与 kernel 共用同一次 clone。

#### Scenario: BSP 目录集成
- **WHEN** 执行 `allwinnera733` 平台的内核构建，`repos.linux-a733` 已声明
- **THEN** 内核源码树中的 `bsp/` 为 `.build/sources/repos/linux-a733/bsp/` 的 symlink 或副本

#### Scenario: kernel/BSP/device 版本一致
- **WHEN** linux-a733 聚合仓库的 `.gitmodules` 声明特定 commit
- **THEN** kernel、BSP、device 三者版本组合由聚合仓库统一管理，不会出现版本漂移

#### Scenario: DTS 文件准备
- **WHEN** config 指定 `kernel_device.board_dts_path` 为 `"configs/cubie_a7z/linux-5.15/board.dts"` 且 `kernel.dts` 为 `"sun60i-a733-cubie-a7z"`
- **THEN** board.dts 从 `.build/sources/repos/linux-a733/device-a733/configs/cubie_a7z/linux-5.15/board.dts` 复制到 `arch/arm64/boot/dts/allwinner/sun60i-a733-cubie-a7z.dts`（内核上游 DTS 目录名保持 `allwinner`，不随 flange 平台重命名而变化）

#### Scenario: BSP DTSI 链接
- **WHEN** BSP 目录的 `configs/linux-5.15/` 包含 DTSI 文件
- **THEN** 这些 DTSI 文件链接到 `arch/arm64/boot/dts/allwinner/` 目录

### Requirement: A733 内核多步 Defconfig 合并
`AllwinnerA733KernelBuilder` 必须（SHALL）支持多步 defconfig 合并。当 `kernel.defconfig` 为列表时，按顺序执行每个 defconfig target。

#### Scenario: 两步 defconfig
- **WHEN** config 中 `kernel.defconfig` 为 `["defconfig", "radxa.config"]`
- **THEN** 构建器依次执行 `make defconfig` 和 `make radxa.config`，最终 `.config` 包含两者合并的结果

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

### Requirement: A733 Bootloader 源码构建模式
`AllwinnerA733BootloaderBuilder` 必须（SHALL）从命名仓库 `u-boot-aw2501` 获取源码，
在构建前应用平台级与板级 bootloader patches，然后编译目标板产物。

#### Scenario: 源码构建
- **WHEN** 执行 `allwinnera733` 平台的 bootloader 构建
- **THEN** 构建器从 `.build/sources/repos/u-boot-aw2501/` 获取源码并执行目标板 `make`
- **AND** 收集 `boot0_sdcard.bin`、`boot0_ufs.bin`、`boot_package.fex` 等产物

#### Scenario: bootloader patches
- **WHEN** 执行 `allwinnera733` 平台的 bootloader 构建
- **THEN** 在编译前应用 `components/platform/allwinnera733/patches/bootloader/*.patch`
- **AND** 应用 `components/board/<board>/patches/bootloader/*.patch`

### Requirement: A733 Recovery Boot 选择
`allwinnera733` 平台必须（SHALL）支持通过 Allwinner RTC reboot flag 或可选
`flange_boot_once=recovery` 在 U-Boot sysboot 前选择本次读取
`/extlinux/recovery.conf`，默认读取 `/extlinux/extlinux.conf`。

#### Scenario: reboot recovery 进入 recovery
- **WHEN** Linux 通过 `reboot("recovery")` 写入 Allwinner recovery reboot flag
- **THEN** A733 U-Boot 清除该 flag 后本次读取 `/extlinux/recovery.conf`
- **AND** 后续普通重启默认读取 `/extlinux/extlinux.conf`

#### Scenario: loader 目标使用 Allwinner bootloader reason
- **WHEN** 设备端执行 `recoveryctl loader`
- **THEN** Allwinner A733 平台传递 Linux reboot reason `bootloader`
- **AND** U-Boot 按 Allwinner 既有 fastboot / loader 流程处理

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

### Requirement: A733 Rootfs 构建
`AllwinnerA733RootfsBuilder` 必须（SHALL）复用 `RootfsBuilder` 基类的通用能力（overlay、firmware、两阶段缓存），
生成 ext4 rootfs.img。若 rootfs 分区 entry 声明 `image_size`，构建器必须（MUST）使用 `image_size`
作为 rootfs.img 的初始大小；若未声明，则保持现有兼容大小策略。

#### Scenario: rootfs 构建流程
- **WHEN** 执行 `allwinnera733` 平台的 rootfs 构建
- **THEN** 完成 Phase 1 (base tarball + apt install) 和 Phase 2 (custom deb + overlay + firmware + 密码设置)，输出 ext4 rootfs.img

#### Scenario: rootfs 使用 image_size
- **WHEN** `allwinnera733` 平台 rootfs 分区配置为 `size: "remaining"` 且 `image_size: "2G"`
- **THEN** `AllwinnerA733RootfsBuilder` 生成 2GB 的 ext4 rootfs.img

### Requirement: A733 整盘镜像组装
`AllwinnerA733ImageBuilder` 必须（SHALL）将 bootloader 固件和分区镜像按 SD 卡分区表布局组装成 raw.img。
若 rootfs 分区 entry 声明 `image_size`，raw.img 中 rootfs GPT 分区初始大小必须（MUST）使用 `image_size`；
`size: "remaining"` 仅表示设备首次启动扩容后的最终容量语义。

#### Scenario: SD 卡镜像组装
- **WHEN** 执行 `allwinnera733` 平台的 image 构建
- **THEN** raw.img 中 boot0_sdcard.bin 写入 sector 256，boot_package.fex 写入 sector 24576，boot.img 和 rootfs.img 写入对应分区 offset

#### Scenario: GPT 分区表
- **WHEN** raw.img 生成完成
- **THEN** 非 raw 类型分区在 GPT 分区表中有对应条目

#### Scenario: rootfs GPT 分区使用 image_size
- **WHEN** `allwinnera733` 平台 rootfs 分区配置为 `size: "remaining"` 且 `image_size: "2G"`
- **THEN** raw.img 中 rootfs GPT 分区初始大小为 2GB
- **AND** raw.img 总大小按初始分区布局计算

### Requirement: A733 平台配置三层继承
`allwinnera733` 平台必须（SHALL）遵循 flange 的三层配置继承体系：platform → SoC → board。PLATFORM 与 SOC 两层之间在目录结构上保持分离（`components/platform/allwinnera733/config.py` + `components/platform/allwinnera733/a733/config.py`），不合并为单一文件。

#### Scenario: 配置合并
- **WHEN** lunch target 为 `radxa-cubie-a7z-default-debug`
- **THEN** 最终配置为 `components/platform/allwinnera733/config.py` → `components/platform/allwinnera733/a733/config.py` → `components/board/radxa-cubie-a7z/config.py` 三层深度合并的结果

#### Scenario: PLATFORM.vendor 字段与平台名一致
- **WHEN** 加载 `components/platform/allwinnera733/config.py`
- **THEN** `PLATFORM.vendor == "allwinnera733"`，与 `board.platform` 字段、`_FLASH_STRATEGIES` 注册键、`builder/platforms/allwinnera733/` 目录名严格一致

#### Scenario: SOC.platform 字段指向新平台名
- **WHEN** 加载 `components/platform/allwinnera733/a733/config.py`
- **THEN** `SOC.platform == "allwinnera733"`，以便 SOC 层知道自己属于哪个平台

### Requirement: A733 平台默认启用 adbd 调试通道
`allwinnera733` 平台必须（SHALL）在 rootfs 中默认装配 `adbd` App，提供基于 USB gadget 的 adb 调试通道，使所有该平台的板开箱具备与 Rockchip 平台对等的调试能力。

#### Scenario: 平台级 App 声明
- **WHEN** 读取 `components/platform/allwinnera733/config.py` 的 `rootfs.custom_packages` 字段
- **THEN** 列表包含字符串 `"adbd"`，使 `AppBuilder.build_all()` 在任意 `allwinnera733` 板的构建中自动为其打包并安装 adbd.deb

#### Scenario: 板级未显式覆盖时的继承
- **WHEN** 某 `allwinnera733` 板的 `components/board/<name>/config.py` 未声明 `rootfs.custom_packages`
- **THEN** 经三层配置合并后，该板的 `custom_packages` 至少包含 `"adbd"`（来自平台层），rootfs 构建产物内 `/usr/bin/adbd` 等文件存在

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
- **WHEN** `components/platform/allwinnera733/a733/config.py` 的 `kernel.defconfig` 列表被 `configure()` 逐项应用
- **THEN** `usb_gadget.config` 在 `radxa.config` 和 `radxa_custom.config` 之后应用，最终 `.config` 中 `CONFIG_USB_CONFIGFS=y`（非 `=m`）

#### Scenario: 最终 `.config` 校验
- **WHEN** 内核构建完成，读取 `.build/sources/repos/linux-a733/src/.config`
- **THEN** `CONFIG_USB_GADGET=y`、`CONFIG_USB_CONFIGFS=y`、`CONFIG_USB_CONFIGFS_F_FS=y`、`CONFIG_CONFIGFS_FS=y` 四项同时成立

### Requirement: A7Z 板级 USB gadget 配置
`components/board/radxa-cubie-a7z/overlay/etc/usbdevice.conf` 必须（SHALL）提供 A733 平台 USB gadget 的 VID/PID、gadget 组名、产品标识等参数，使 `usbdevice.service` 启动时能正确组装 configfs gadget 树。

#### Scenario: VID 使用 Allwinner 官方值
- **WHEN** 读取 A7Z rootfs 中 `/etc/usbdevice.conf`
- **THEN** `USB_VENDOR_ID=0x1f3a`（Allwinner Technology 注册 VID），使设备在宿主机 `lsusb` 中显示厂商为 "Allwinner Technology"

#### Scenario: USB_GROUP 与 sunxi 命名空间一致
- **WHEN** `usbdevice start` 在 A7Z 上执行
- **THEN** configfs gadget 路径为 `/sys/kernel/config/usb_gadget/sunxi/`，与 Allwinner sunxi 生态命名对齐（此命名空间源自内核 BSP，与 flange 平台名无关）

#### Scenario: 默认启用 adb function
- **WHEN** A7Z 首次启动且无 `/etc/usbdevice.d/` 用户扩展
- **THEN** `USB_FUNCS=adb`，宿主机执行 `adb devices` 可识别到设备并进入 shell

### Requirement: A733 直接使用 linux-a733 原始 patches
`AllwinnerA733KernelBuilder` 必须（SHALL）直接应用 `.build/sources/repos/linux-a733/debian/patches/` 中的原始补丁，不再维护手动适配 `src/` 前缀的自定义版本。

#### Scenario: patches 从聚合仓库应用
- **WHEN** 执行 `allwinnera733` 平台的内核构建
- **THEN** 按 `.build/sources/repos/linux-a733/debian/patches/series` 声明的顺序应用补丁

#### Scenario: patch 应用目录是聚合仓库根
- **WHEN** 应用含 `a/src/...` 和 `a/bsp/...` 路径的补丁
- **THEN** patch 在 `.build/sources/repos/linux-a733/` 根目录应用，路径前缀自然匹配（无需 -p2 或路径改写）

#### Scenario: patches 顺序由 series 文件决定
- **WHEN** `debian/patches/series` 列出 4 个补丁
- **THEN** 按 series 文件声明顺序应用，任一失败则构建失败

### Requirement: A733 bootloader 复用 u-boot-aw2501 命名仓库
`AllwinnerA733BootloaderBuilder` 必须（SHALL）通过 `from_repo: "u-boot-aw2501"` 引用命名仓库获取源码，不再使用组件级独立 `repo` 配置。

#### Scenario: bootloader 从命名仓库构建
- **WHEN** 执行 `allwinnera733` 平台的 bootloader 构建
- **THEN** 源码目录为 `.build/sources/repos/u-boot-aw2501/`（含所有子模块）

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
- **WHEN** `components/platform/allwinnera733/a733/config.py` 的 `kernel.defconfig` 列表被 `configure()` 逐项应用
- **THEN** `aic8800_wlan.config` 在 `radxa.config` 和 `radxa_custom.config` 之后应用
- **AND** `aic8800_wlan.config` 在 `case_insensitive_fix.config` 之前应用

#### Scenario: 最终内核配置启用 USB 模式
- **WHEN** 内核构建完成，读取 `.build/sources/repos/linux-a733/src/.config`
- **THEN** `CONFIG_AIC_WLAN_SUPPORT=y`
- **AND** `CONFIG_AIC8800_USB=y`
- **AND** `CONFIG_AIC8800_SDIO` 未启用
- **AND** `CONFIG_AIC_LOADFW_SUPPORT=m`
- **AND** `CONFIG_AIC8800_WLAN_SUPPORT=m`

### Requirement: A733 AIC8800 modules 产物收集
`allwinnera733` 平台的 kernel 构建必须（SHALL）通过 `modules_install` 收集 AIC8800 USB 驱动模块，并保留
Linux kernel module dependency（模块依赖）索引文件，以便 rootfs 中的 `modprobe` 可解析依赖。

#### Scenario: kernel 产物包含 AIC8800 USB 模块
- **WHEN** 执行 `flange build kernel`
- **THEN** kernel 产物目录 `kernel/modules/lib/modules/<kernelrelease>/` 包含 `aic_load_fw` 模块
- **AND** 包含 `aic8800_fdrv` 模块
- **AND** 包含 `modules.dep`
- **AND** 包含 `modules.alias`

#### Scenario: AIC8800 USB alias 可用于自动匹配
- **WHEN** kernel 产物中的 `modules.alias` 生成完成
- **THEN** 文件中包含 AIC8800 USB 设备可匹配的 `usb:` alias
- **AND** 该 alias 指向 AIC8800 驱动模块

### Requirement: A733 rootfs 模块管理、诊断和 Wi-Fi 连接能力
`allwinnera733` 平台 normal rootfs 必须（SHALL）安装 `kmod`、`usbutils`、`net-tools` 和 `wpasupplicant`，
使目标设备具备标准 `modprobe`、`insmod`、`depmod`、`lsusb`、`ifconfig` 和 Wi-Fi supplicant（认证客户端）能力。

#### Scenario: rootfs apt 包包含模块和诊断工具
- **WHEN** 读取 `components/platform/allwinnera733/config.py` 的 `rootfs.packages`
- **THEN** 列表包含字符串 `"kmod"`
- **AND** 列表包含字符串 `"usbutils"`
- **AND** 列表包含字符串 `"net-tools"`
- **AND** 列表包含字符串 `"wpasupplicant"`

#### Scenario: rootfs 中存在模块管理、诊断和 Wi-Fi 连接命令
- **WHEN** 执行 `allwinnera733` 平台的 rootfs 构建
- **THEN** rootfs 中存在 `modprobe` 命令
- **AND** rootfs 中存在 `insmod` 命令
- **AND** rootfs 中存在 `depmod` 命令
- **AND** rootfs 中存在 `lsusb` 命令
- **AND** rootfs 中存在 `ifconfig` 命令
- **AND** rootfs 中存在 `wpa_supplicant` 命令

### Requirement: A733 rootfs 安装 kernel modules
`AllwinnerA733RootfsBuilder` 必须（SHALL）将 kernel 组件收集到的 `lib/modules` 子树安装进 normal rootfs 的
`/lib/modules/`，使 AIC8800 USB 模块随 rootfs 镜像交付。

#### Scenario: rootfs 包含 kernel release 模块目录
- **WHEN** 执行 `flange build rootfs`
- **THEN** rootfs 镜像内存在 `/lib/modules/<kernelrelease>/`
- **AND** 该目录包含 `modules.dep`
- **AND** 该目录包含 `modules.alias`

#### Scenario: rootfs 包含 AIC8800 USB 模块
- **WHEN** 执行 `flange build rootfs`
- **THEN** rootfs 镜像内 `/lib/modules/<kernelrelease>/` 包含 `aic_load_fw` 模块
- **AND** 包含 `aic8800_fdrv` 模块

### Requirement: Radxa Cubie A7Z AIC8800 固件安装约定
启用 AIC8800 USB 的 Radxa Cubie A7Z 板级配置必须（SHALL）通过 `rootfs.extra_firmware` 从 Radxa `aic8800`
仓库安装 AIC8800D80 USB 固件到 rootfs 的 `/lib/firmware/aic8800_fw/USB/`，并与 USB firmware helper 参数保持一致。

#### Scenario: 板级配置声明 Radxa AIC8800 固件来源
- **WHEN** 读取 `components/board/radxa-cubie-a7z/config.py`
- **THEN** `rootfs.extra_firmware` 至少声明一个名为 `radxa-aic8800` 的固件条目
- **AND** 该条目的 `repo` 指向 `https://github.com/radxa-pkg/aic8800.git`
- **AND** 该条目固定 `commit`
- **AND** 该条目的 `repo_subdir` 指向 `src/USB/driver_fw/fw`
- **AND** 该条目的 `dest` 为 `lib/firmware/aic8800_fw/USB`

#### Scenario: 固件路径与模块参数一致
- **WHEN** 板级 overlay 提供 `/etc/modprobe.d/aic8800.conf`
- **THEN** 文件中声明 `options aic_load_fw aic_fw_path=/lib/firmware/aic8800_fw/USB`
- **AND** rootfs 中 AIC8800 固件安装目标路径为 `/lib/firmware/aic8800_fw/USB/`

#### Scenario: AIC8800D80 固件同时满足 loader 和 fdrv 路径
- **WHEN** 执行 Radxa Cubie A7Z rootfs 构建
- **THEN** rootfs 中存在 `/lib/firmware/aic8800_fw/USB/fmacfw_8800d80_u02.bin`
- **AND** rootfs 中存在 `/lib/firmware/aic8800_fw/USB/fw_patch_8800d80_u02.bin`
- **AND** rootfs 中存在 `/lib/firmware/aic8800_fw/USB/fw_patch_table_8800d80_u02.bin`
- **AND** rootfs 中存在 `/lib/firmware/aic8800_fw/USB/aic8800D80/aic_userconfig_8800d80.txt`

#### Scenario: 声明的固件缺失时构建失败
- **WHEN** 板级配置通过 `rootfs.extra_firmware` 声明 AIC8800 固件文件
- **AND** 固件仓库中缺少任一声明文件
- **THEN** rootfs 构建失败并提示缺失的固件文件路径

### Requirement: Radxa Cubie A7Z AIC8800 USB 实机验证
Radxa Cubie A7Z 的 AIC8800 USB 支持必须（SHALL）通过刷写后的实机验证确认，确保 USB 枚举、固件加载、
驱动 probe 和 Wi-Fi 网络接口均工作。

#### Scenario: 刷写后 Wi-Fi 接口可用
- **WHEN** 将包含 Radxa AIC8800 USB 固件的 kernel/rootfs 或整盘镜像刷写到 Radxa Cubie A7Z
- **AND** 设备启动到 normal rootfs
- **THEN** `lsusb` 可看到 `a69c:8d81 AICSemi AIC 8800D80`
- **AND** `dmesg` 中不再出现 `usb 3-1: can't set config #1, error -110`
- **AND** `dmesg` 中出现 AIC8800 Wi-Fi interface 创建日志
- **AND** `ip link` 或 NetworkManager 可看到 Wi-Fi 网络接口

### Requirement: A733 AIC8800 模块加载策略
启用 AIC8800 USB 的 A733 板必须（SHALL）支持通过 `modprobe aic8800_fdrv` 手动加载 Wi-Fi 驱动，并可以通过
板级 overlay 声明开机自动加载策略。

#### Scenario: modprobe 加载 AIC8800 Wi-Fi
- **WHEN** 目标设备启动到 normal rootfs
- **AND** 执行 `modprobe aic8800_fdrv`
- **THEN** `modprobe` 根据 `/lib/modules/<kernelrelease>/modules.dep` 自动加载所需依赖模块
- **AND** AIC8800 Wi-Fi 驱动开始探测 USB 设备

#### Scenario: 板级 overlay 声明自动加载
- **WHEN** 板级 overlay 提供 `/etc/modules-load.d/aic8800.conf`
- **THEN** rootfs 构建产物包含该文件
- **AND** 文件至少声明 `aic_load_fw` 和 `aic8800_fdrv`
