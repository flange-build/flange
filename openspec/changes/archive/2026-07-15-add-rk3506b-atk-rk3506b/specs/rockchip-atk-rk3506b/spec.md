## ADDED Requirements

### Requirement: RK3506B SoC 与 ATK board 可被配置系统发现

项目 SHALL 提供 `components/platform/rockchip/rk3506b/config.py` 的 `SOC` 和
`components/board/atk-rk3506b/config.py` 的 `BOARD`，使 lunch target
`atk-rk3506b-default-{debug,release}` 可由三层配置自动发现与解析。合并配置 SHALL 声明
`platform=rockchip`、`soc=rk3506b`、`board=atk-rk3506b`、`arch=armhf`。

#### Scenario: lunch target 可解析
- **WHEN** 解析 `atk-rk3506b-default-debug`
- **THEN** 返回合法 FINAL_CONFIG，且 platform、soc、board、arch 字段与目标板一致

#### Scenario: board 接入不使用板名硬编码
- **WHEN** 检查 builder 代码
- **THEN** 不存在以 `atk-rk3506b` 板名决定架构、文件系统或刷写策略的条件分支

### Requirement: ATK-RK3506B 使用指定内核分支与 DTS

合并配置 SHALL 固定 kernel repo 为
`ssh://git@gitlab-r.eric3u.xyz:20022/argon/kernel.git`、branch 为
`linux-6.1-stan-rkr5.1`、DTS 为
`rk3506b-alientek-mipi720x1280-nand-ubi-ubifs-amp-linux`。defconfig 顺序 SHALL 包含
`rk3506_defconfig`、`rk3506-display.config`、`rockchip_amp.config` 及平台要求的兼容 fragment，
并启用 `CONFIG_RPMSG_CHAR`、`CONFIG_RPMSG_CTRL`、MTD、UBI 和 UBIFS。

#### Scenario: 内核配置与设备树精确匹配
- **WHEN** 解析 board kernel 配置并构建 DTB
- **THEN** repo、branch 和 DTS 与要求逐字一致
- **AND** 最终 `.config` 支持 MIPI display、AMP、SPI NAND、UBI/UBIFS 与 RPMsg char

#### Scenario: 以太网驱动与 PHY 支持内建
- **WHEN** 解析 debug 或 release 的最终 kernel defconfig
- **THEN** `CONFIG_DWMAC_ROCKCHIP`、`CONFIG_STMMAC_ETH`、
  `CONFIG_STMMAC_PLATFORM`、`CONFIG_MOTORCOMM_PHY`、`CONFIG_PHYLIB`、
  `CONFIG_MDIO_BUS` 与 `CONFIG_FIXED_PHY` 均为 `y`
- **AND** 上述配置不被通用 `rk3506_defconfig` 降级为 module

#### Scenario: DTS 保留 CPU2 AMP 与 UBI 启动参数
- **WHEN** 反编译构建出的目标 DTB
- **THEN** Linux CPU 列表不含 `cpu@f02`
- **AND** `chosen.bootargs` 含 `ubi.mtd=5 root=ubi0:rootfs rootfstype=ubifs`

### Requirement: ATK-RK3506B 使用 RK3506B U-Boot 与 rkbin 配置

bootloader 配置 SHALL 使用项目选定的 Radxa U-Boot/rkbin 固定分支，并通过 board patch 原样
引入 ATK tag 的 `alientek_rk3506_defconfig`、`alientek-rk3506.dts` 与 DTB Makefile 条目。
ATK board SHALL 按原厂目标配置合并 `alientek_rk3506_defconfig` 与 `rk-amp.config`，使用
`RK3506BMINIALL.ini` 和 `RK3506TOS.ini`。builder SHALL 从 TOS INI 取得 TEE，而不是要求
不存在的 BL31，并通过 `boot_merger` 收集 loader 与 NEWIDB 输出；`FlashBoot` SHALL 替换为
本次源码构建的 `spl/u-boot-spl.bin`，不得继续混用 rkbin 预编 SPL。

#### Scenario: ARM32 U-Boot 与 AMP 选项构建成功
- **WHEN** 构建 ATK-RK3506B bootloader
- **THEN** 使用 `/opt/arm-linux-gcc10/bin/arm-none-linux-gnueabihf-` 的 gcc-10.3.1
  ARM32 toolchain 产出 loader、idbloader 和 `u-boot.itb`
- **AND** 最终 U-Boot 配置同时含 `CONFIG_AMP=y` 与 `CONFIG_ROCKCHIP_AMP=y`
- **AND** `CONFIG_DEFAULT_DEVICE_TREE="alientek-rk3506"`、
  `CONFIG_ROCKCHIP_HWID_DTB=y` 且 `CONFIG_SPL_AB` 关闭
- **AND** loader 内的 SPL banner 来自当前 U-Boot 源码，而非 INI 原始预编 `FlashBoot`

#### Scenario: U-Boot FIT 遵循原厂固定槽位与双副本布局
- **WHEN** 为 ATK-RK3506B 打包 U-Boot FIT
- **THEN** `mkimage` external data offset 为 `0x1200`
- **AND** 单槽为 2048 KiB、共两份，最终 `u-boot.itb` 为 4 MiB
- **AND** 第二份 FIT 在 2 MiB 偏移具有有效 FDT magic

#### Scenario: TOS-only INI 不按 BL31 解析
- **WHEN** bootloader builder 处理 `RK3506TOS.ini`
- **THEN** `TOSTA` 指向的固件被作为 TEE 输入
- **AND** 不因缺少 BL31/BL32 section 失败

#### Scenario: vendor FIT 在 Android fallback 前取得 SPI NAND bootdev
- **WHEN** `RKIMG_BOOTCOMMAND` 依次执行 `boot_fit` 与 `boot_android`
- **THEN** FIT、resource、boot mode 与 vendor storage 使用 `rockchip_get_bootdev()` 读取 MTD
- **AND** 不依赖尚未由 `boot_android` 初始化的 `android_dev_desc`
- **AND** 不改走 extlinux/ext4 boot 分区

### Requirement: ATK-RK3506B 硬件容量与 SPI NAND 布局受校验

board 配置 SHALL 声明 512 MiB DDR 和 512 MiB SPI NAND，关闭 ext4 recovery，并沿用 RK3566
AMP target 的 GPT 分区顺序。`parameter.txt` SHALL 由仓库内 `partitions.entries` 生成，不依赖
板外文件；UBI 几何 SHALL 来自原厂 SDK 或实机证据。rootfs SHALL 是第六个 MTD 分区以满足
`ubi.mtd=5`，且 `amp` SHALL 位于 rootfs 之前。实机 loader 不支持 `SSD` 存储切换，因此 board
SHALL NOT 设置 `flash_storage`，刷写 strategy SHALL 保持 loader 当前 SPI NAND。

#### Scenario: GPT 配置生成的分区顺序满足 mtd5
- **WHEN** 从板级 `partitions.entries` 生成并解析 `parameter.txt`
- **THEN** `rootfs` 的零基 MTD index 为 5
- **AND** `amp` 是 rootfs 之前的具名 `mtd4` 分区
- **AND** parameter 头部声明 `TYPE: GPT`

#### Scenario: recovery 不参与构建和刷写
- **WHEN** 构建 ATK-RK3506B image
- **THEN** 不要求 recovery rootfs 或 ext4 recovery image
- **AND** 即使原厂布局保留 recovery 占位，也不向其写入 flange recovery 镜像

#### Scenario: 单介质 loader 直接进入具名 DI 路由
- **WHEN** 生成 ATK-RK3506B 的 `flash-config.json`
- **THEN** `storage_type` 为 `spinand` 且 `storage` 为空
- **AND** `idbloader` 不在具名 DI 清单中
- **AND** MaskROM 下临时 `DB` 核验设备身份，执行 `UL miniloader -noreset` 后不执行 `SSD`
- **AND** 直接下发 parameter 与具名分区镜像

#### Scenario: 单刷 bootloader 同时更新 SPL 与 proper
- **WHEN** 对 SPI NAND target 执行 `flange flash bootloader`
- **THEN** 先执行 `UL miniloader -noreset` 更新同源 SPL
- **AND** 随后只执行 `DI -uboot`，不写 boot、amp 或 rootfs

### Requirement: ATK-RK3506B 冷启动可用 USB gadget/ADB

ATK-RK3506B rootfs SHALL 在 `usbdevice.service` 之前按原厂 SDK 顺序加载
`phy-rockchip-inno-usb2`、`usb_f_fs` 与 `dwc2`，并确保 ConfigFS 已挂载。
`usb_f_fs` SHALL 通过模块依赖注册 `libcomposite` 与 `usb_gadget` 子系统。
USB0 SHALL 保持 `dr_mode="otg"` 且在 device role 下绑定 `ff740000.usb`；
USB1 SHALL 保持 host 用途。运行时脚本 SHALL 能自愈未加载的 modular
gadget framework，并且不应因最小 rootfs 缺少 `fuser` 而启动失败。

#### Scenario: 无手工 modprobe 的冷启动枚举
- **WHEN** 重刷 rootfs 并在 USB0 连接主机的情况下冷启动
- **THEN** `/sys/kernel/config/usb_gadget` 自动存在
- **AND** gadget `UDC` 内容为 `ff740000.usb`
- **AND** `/sys/class/udc/ff740000.usb/state` 进入 `configured` 且 ADB 可连接

#### Scenario: gadget framework 缺失有可操作诊断
- **WHEN** ConfigFS 已挂载但 `usb_gadget` 子系统未注册
- **THEN** `usbdevice` 尝试加载 `usb_f_fs`
- **AND** 仍失败时报告 gadget framework 未注册，不误报为特定
  DWC3/PD controller 故障

### Requirement: ATK-RK3506B 输出可分区刷写的完整产物集

成功的完整构建 SHALL 至少输出 miniloader、idbloader、U-Boot、FIT `boot.img`、
`amp.img`、`rootfs.ubi`、由配置生成的 `parameter.txt`、具名刷写 manifest 和
`flash-config.json`。SPI NAND 路径 SHALL NOT 生成整片 `raw.img`。

#### Scenario: release 产物完整
- **WHEN** 完成 `atk-rk3506b-default-release` 构建
- **THEN** 所有必需的 loader 与分区镜像存在并通过格式/容量校验
- **AND** flash 清单中的每个镜像均能映射到 GPT 配置生成的具名分区

### Requirement: ATK-RK3506B 刷写前验证设备与布局身份

flash config SHALL 记录 `soc=rk3506b`、parameter SHA-256，以及可精确匹配 RK3506
RCI 标记 `46 30 35 33`/`F053` 和 SPI NAND 介质类别 `SNAND` 的身份规则。
RFI/RID 中不稳定的厂商名和 JEDEC 字段 MUST NOT 作为单介质 loader 的必选门禁。
刷写策略 SHALL 强制仅连接一台 Rockchip 设备，并在首次持久写入前通过
`RCI/RFI/RID` 验证芯片与介质类别。

#### Scenario: 接错板或 parameter 漂移时拒绝刷写
- **WHEN** SoC/存储身份、parameter 摘要或分区 offset/size 任一不匹配
- **THEN** 刷写在 `UL/DI/WL` 前失败

### Requirement: 可提交配置不得包含开发机绝对路径

SoC/board 配置 SHALL 记录远程 repo 与 branch，不得记录开发机 kernel clone 或其他本地绝对
路径。本地 clone MAY 通过未提交的 local source override 使用。

#### Scenario: 配置可移植
- **WHEN** 在仓库中搜索 ATK-RK3506B 配置和文档
- **THEN** 可提交配置不含用户主目录绝对路径

### Requirement: ATK-RK3506B 支持 USB GUD 主机显示

ATK-RK3506B 的最终 kernel defconfig SHALL 启用
`CONFIG_DRM_GUD=y`，并保持 USB1 为 Host。USB0 的 OTG/device 与 ADB 配置不得因启用 GUD
而改变。

#### Scenario: GUD 内核配置合并
- **WHEN** 解析 `atk-rk3506b-default-debug` 或 `atk-rk3506b-default-release`
- **THEN** 最终 kernel defconfig 包含 `CONFIG_DRM_GUD=y`
- **AND** 最终 kernel defconfig 包含 `CONFIG_DRM_FBDEV_EMULATION=y` 与
  `CONFIG_FB=y`、`CONFIG_VT=y`、`CONFIG_VT_CONSOLE=y`、`CONFIG_FRAMEBUFFER_CONSOLE=y`
- **AND** kernel args 包含 `console=tty1 fbcon=map:1`
- **AND** USB1 仍用于连接 USB Host 设备
- **AND** USB0 仍用于 OTG/device 与 ADB

### Requirement: ATK-RK3506B 支持 Cardputer USB HID 与 UAC1

ATK-RK3506B 的最终 kernel defconfig SHALL 启用 `CONFIG_USB_HID=m` 与
`CONFIG_SND_USB_AUDIO=m`，使 Cardputer USB 复合设备的 HID 键盘、UAC1 扬声器与麦克风
接口能够通过 USB modalias 自动绑定。rootfs SHALL 包含 `evtest` 与 `alsa-utils`
验收工具。为遵守 414 MiB UBI 容量门禁，该板 debug 包集 SHALL 保留
`gdb`/`strace`/`tcpdump` 但不安装 `valgrind`。

#### Scenario: Cardputer 复合设备自动绑定
- **WHEN** 将 Cardputer `16d0:10a9` 连接到 USB1 Host 口
- **THEN** HID Boot Keyboard 接口绑定 `usbhid` 并创建 `/dev/input/eventN`
- **AND** AudioControl/AudioStreaming 接口绑定 `snd-usb-audio`
- **AND** ALSA 列出 mono 16 kHz / 16 bit playback 与 capture PCM
- **AND** rootfs 可执行 `evtest`、`aplay`、`arecord` 与 `amixer`
