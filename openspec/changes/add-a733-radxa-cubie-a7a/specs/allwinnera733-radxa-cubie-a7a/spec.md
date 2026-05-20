## ADDED Requirements

### Requirement: radxa-cubie-a7a board 配置基础字段

`components/board/radxa-cubie-a7a/config.py` MUST 导出 `BOARD` 字典，并在顶层声明以下字段：

- `BOARD["board"]` MUST 等于字符串 `"radxa-cubie-a7a"`
- `BOARD["soc"]` MUST 等于字符串 `"a733"`
- `BOARD["platform"]` MUST 等于字符串 `"allwinnera733"`
- `BOARD["kernel"]["dts"]` MUST 等于字符串 `"sun60i-a733-cubie-a7a"`
- `BOARD["kernel_device"]["board_dts_path"]` MUST 等于字符串 `"configs/cubie_a7a/linux-5.15/board.dts"`
- `BOARD["bootloader"]["target"]` MUST 等于字符串 `"radxa-cubie-a7a"`

board config MUST NOT 覆盖 `kernel.defconfig`、`kernel.oot_modules`、`kernel.branch`、`kernel.repo`、`bootloader.toolchain_tarball`、`bootloader.toolchain_url`、`bootloader.riscv_tarball`、`bootloader.riscv_url`、`partitions`、`rootfs.url`、`boot.dtb_filename`、`boot.kernel_args` 等 SoC 层字段；全部沿用 `components/platform/allwinnera733/a733/config.py` 的 SoC 层取值。

#### Scenario: 三层合并后 board 字段正确

- **WHEN** 调用 `get_board_config("radxa-cubie-a7a")`
- **THEN** 返回字典的 `board` 字段为 `"radxa-cubie-a7a"`
- **AND** `soc` 字段为 `"a733"`
- **AND** `platform` 字段为 `"allwinnera733"`
- **AND** `kernel.dts` 字段为 `"sun60i-a733-cubie-a7a"`
- **AND** `kernel_device.board_dts_path` 字段为 `"configs/cubie_a7a/linux-5.15/board.dts"`
- **AND** `bootloader.target` 字段为 `"radxa-cubie-a7a"`

#### Scenario: board 不覆盖 SoC kernel 字段

- **WHEN** 调用 `get_board_config("radxa-cubie-a7a")`
- **THEN** 返回字典的 `kernel.defconfig` 等于 SoC 层 `a733` 声明的列表 `["defconfig", "bsp_defconfig", "radxa.config", "radxa_custom.config", "aic8800_wlan.config", "usb_gadget.config", "panel_mipi_dbi.config", "case_insensitive_fix.config"]`
- **AND** `kernel.oot_modules` 等于 SoC 层声明（含 `img-bxm (PowerVR BXM GPU)` 一条）

#### Scenario: board 不覆盖 SoC bootloader 工具链与 partitions

- **WHEN** 调用 `get_board_config("radxa-cubie-a7a")`
- **THEN** 返回字典的 `bootloader.toolchain_tarball` 等于 SoC 层 `"gcc-linaro-7.2.1-2017.11-x86_64_arm-linux-gnueabi.tar.xz"`
- **AND** `partitions.entries` 与 SoC 层 a733 声明的六条 entry 完全一致（boot0 / boot0_ufs / boot_package / boot / recovery / rootfs）

### Requirement: radxa-cubie-a7a vendor overlay 复用 a7z 全集减一

`BOARD["boot"]["vendor_overlays"]` MUST 声明以下两组 overlay：

- 全部 13 条 `sun60iw2p1-*` SoC 级 overlay（与 a7z 同名同顺序，含 i2s0-2ch / i2s4-2ch / pwm1-{1,2,3,6,7} / spi1-spidev / spi3-spidev / twi2 / twi7 / uart2 / uart3 / uart4）
- 全部 7 条 `cubie-a7a-*` 板级 overlay：`cubie-a7a-enable-sunxi-ac101-sound-card.dtbo`、`cubie-a7a-radxa-25w-poe.dtbo`、`cubie-a7a-radxa-camera-8m-219.dtbo`、`cubie-a7a-radxa-camera-13m-214.dtbo`、`cubie-a7a-radxa-camera-4k-415.dtbo`、`cubie-a7a-radxa-display-8hd.dtbo`、`cubie-a7a-radxa-display-10fhd.dtbo`

`BOARD["boot"]["vendor_overlays"]` MUST NOT 包含 `cubie-a7z-reroute-audio-from-hdmi-to-typec-dp.dtbo`（a7z 私有，a7a 板载 AC101B 直挂，不需要 HDMI→TypeC-DP 音频 reroute）。

#### Scenario: vendor_overlays 含全部 sun60iw2p1 SoC 级 overlay

- **WHEN** 调用 `get_board_config("radxa-cubie-a7a")` 并读取 `boot.vendor_overlays`
- **THEN** 列表含 `sun60iw2p1-i2s0-2ch.dtbo`、`sun60iw2p1-i2s4-2ch.dtbo`、`sun60iw2p1-pwm1-1.dtbo`、`sun60iw2p1-pwm1-2.dtbo`、`sun60iw2p1-pwm1-3.dtbo`、`sun60iw2p1-pwm1-6.dtbo`、`sun60iw2p1-pwm1-7.dtbo`、`sun60iw2p1-spi1-spidev.dtbo`、`sun60iw2p1-spi3-spidev.dtbo`、`sun60iw2p1-twi2.dtbo`、`sun60iw2p1-twi7.dtbo`、`sun60iw2p1-uart2.dtbo`、`sun60iw2p1-uart3.dtbo`、`sun60iw2p1-uart4.dtbo`

#### Scenario: vendor_overlays 含全部 cubie-a7a 板级 overlay

- **WHEN** 调用 `get_board_config("radxa-cubie-a7a")` 并读取 `boot.vendor_overlays`
- **THEN** 列表含 `cubie-a7a-enable-sunxi-ac101-sound-card.dtbo`
- **AND** 含 `cubie-a7a-radxa-25w-poe.dtbo`
- **AND** 含 `cubie-a7a-radxa-camera-8m-219.dtbo`
- **AND** 含 `cubie-a7a-radxa-camera-13m-214.dtbo`
- **AND** 含 `cubie-a7a-radxa-camera-4k-415.dtbo`
- **AND** 含 `cubie-a7a-radxa-display-8hd.dtbo`
- **AND** 含 `cubie-a7a-radxa-display-10fhd.dtbo`

#### Scenario: vendor_overlays 不含 a7z 私有 reroute overlay

- **WHEN** 调用 `get_board_config("radxa-cubie-a7a")` 并读取 `boot.vendor_overlays`
- **THEN** 列表不含 `cubie-a7z-reroute-audio-from-hdmi-to-typec-dp.dtbo`

#### Scenario: 实机 boot 分区含 a7a 板级 overlay 而无 a7z reroute

- **WHEN** 构建 `radxa-cubie-a7a-default-debug` 后挂载 boot.img
- **THEN** `/dtbs/allwinner/overlay/cubie-a7a-enable-sunxi-ac101-sound-card.dtbo` 存在
- **AND** `/dtbs/allwinner/overlay/cubie-a7z-reroute-audio-from-hdmi-to-typec-dp.dtbo` 不存在

### Requirement: radxa-cubie-a7a 不携带板级 dtso / board_overlays / panel firmware

`components/board/radxa-cubie-a7a/` 目录 MUST NOT 包含以下子目录与文件：

- `dtso/` 子目录（a7a 主显示走 MIPI DSI + HDMI 直出，无 ST7789V SPI 小屏）
- `firmware/panel/` 子目录（无 MIPI DBI SPI 屏）
- `patches/` 子目录（首版无板私有 patch）

`BOARD["boot"]["board_overlays"]` MUST 不声明，或声明为空列表 `[]`。

`BOARD["rootfs"]` MUST NOT 含 `panel_firmware` 键。

#### Scenario: board 目录无 dtso

- **WHEN** 检查 `components/board/radxa-cubie-a7a/` 目录树
- **THEN** 不存在 `dtso/` 子目录
- **AND** 不存在任何 `.dtso` 后缀文件

#### Scenario: board 目录无 panel firmware

- **WHEN** 检查 `components/board/radxa-cubie-a7a/` 目录树
- **THEN** 不存在 `firmware/panel/` 子目录

#### Scenario: board 目录无 patches

- **WHEN** 检查 `components/board/radxa-cubie-a7a/` 目录树
- **THEN** 不存在 `patches/` 子目录

#### Scenario: 三层合并后 board_overlays 为空

- **WHEN** 调用 `get_board_config("radxa-cubie-a7a")`
- **THEN** `boot.board_overlays` 不存在，或值为空列表 `[]`

#### Scenario: 三层合并后 rootfs.panel_firmware 不存在

- **WHEN** 调用 `get_board_config("radxa-cubie-a7a")`
- **THEN** 返回字典的 `rootfs` 块不含 `panel_firmware` 键

### Requirement: radxa-cubie-a7a 默认 overlay 仅启板载音频

`BOARD["boot"]["default_overlays"]` MUST 等于列表 `["cubie-a7a-enable-sunxi-ac101-sound-card.dtbo"]`。

该默认列表 MUST NOT 含 `sun60iw2p1-spi1-st7789v-display.dtbo`（a7a 无 SPI 小屏）、camera 或 display 类 overlay（a7a 默认走 HDMI 直出，DSI 屏需具体 panel init 序列方可点亮，首版不开）。

#### Scenario: default_overlays 仅一项

- **WHEN** 调用 `get_board_config("radxa-cubie-a7a")` 并读取 `boot.default_overlays`
- **THEN** 列表长度为 1
- **AND** 唯一一项为 `cubie-a7a-enable-sunxi-ac101-sound-card.dtbo`

#### Scenario: 实机首启 extlinux 默认应用音频 overlay

- **WHEN** 实机首启后读取 `/boot/extlinux/extlinux.conf`
- **THEN** `fdtoverlays` 行含 `cubie-a7a-enable-sunxi-ac101-sound-card.dtbo`

#### Scenario: 实机 ALSA 列出板载 AC101B 声卡

- **WHEN** 实机首启后执行 `aplay -l`
- **THEN** 输出含 `sunxi-ac101b` 字样的 card

### Requirement: radxa-cubie-a7a AIC8800 D80 USB Wi-Fi 链路沿用 a7z

`BOARD["wifi"]["aic8800_usb"]` MUST 等于 `True`。

`BOARD["rootfs"]["+extra_firmware"]` MUST 含两条 entry，分别对应 AIC8800 D80 USB 固件的"扁平目录"与"芯片子目录"两套部署，逐字段与 `radxa-cubie-a7z` 同名字段一致：

- 第一条：`name="radxa-aic8800"`、`repo="https://github.com/radxa-pkg/aic8800.git"`、`commit="7f42b22913b462ab6c658dfc075bae1dbfe9a71a"`、`repo_subdir="src/USB/driver_fw/fw/aic8800D80"`、`dest="lib/firmware/aic8800_fw/USB"`，`files` 含 15 项 AIC8800 D80 USB 固件文件名
- 第二条：`name="radxa-aic8800"`、`repo` / `commit` / `dest` 同上，`repo_subdir="src/USB/driver_fw/fw"`、`files` 为 15 项文件名各加 `aic8800D80/` 前缀的列表（fdrv 在该路径下拼接子目录读取用户配置）

两条 entry MUST 与 `components/board/radxa-cubie-a7z/config.py` 同名字段 1:1 等价。

#### Scenario: extra_firmware 两条 entry

- **WHEN** 调用 `get_board_config("radxa-cubie-a7a")` 并读取 `rootfs.+extra_firmware`
- **THEN** 列表长度为 2
- **AND** 两条 entry 的 `name` 均为 `"radxa-aic8800"`
- **AND** 两条 entry 的 `commit` 均为 `"7f42b22913b462ab6c658dfc075bae1dbfe9a71a"`
- **AND** 两条 entry 的 `dest` 均为 `"lib/firmware/aic8800_fw/USB"`

#### Scenario: extra_firmware 与 a7z 等价

- **WHEN** 比较 `radxa-cubie-a7a` 与 `radxa-cubie-a7z` 的 `BOARD["rootfs"]["+extra_firmware"]`
- **THEN** 两块板的两条 entry 各字段（`name` / `repo` / `commit` / `repo_subdir` / `files` / `dest`）完全相同

#### Scenario: rootfs 含 AIC8800 D80 USB 固件

- **WHEN** 构建 `radxa-cubie-a7a-default-debug` 的 rootfs 组件并 mount 产物镜像
- **THEN** `/lib/firmware/aic8800_fw/USB/fw_patch_8800d80_u02.bin` 存在且非空
- **AND** `/lib/firmware/aic8800_fw/USB/aic8800D80/fw_patch_8800d80_u02.bin` 存在且非空

#### Scenario: 实机 USB Wi-Fi 模块识别

- **WHEN** 实机首启后查看 `lsmod`
- **THEN** 输出含 `aic_load_fw` 与 `aic8800_fdrv`
- **AND** `ip link` 输出含 `wlan0`

### Requirement: radxa-cubie-a7a overlay 文件契约

`components/board/radxa-cubie-a7a/overlay/etc/` 目录 MUST 包含以下文件：

- `usbdevice.conf` MUST 声明 `USB_VENDOR_ID=0x1f3a`（Allwinner 官方 VID）、`USB_PRODUCT_NAME="radxa-cubie-a7a"`、`USB_MANUFACTURER="Allwinner"`、`USB_GROUP=sunxi`、`USB_FUNCS=adb`、`USB_SERIAL_SOURCE=cpuinfo`、`USB_BCD_DEVICE=0x0310`、`USB_BCD_USB=0x0200`、`USB_MAX_POWER=500`、`USB_PID_adb=0x0006`、`USB_PID_DEFAULT=0x0019`
- `modules-load.d/aic8800.conf` MUST 含两行：`aic_load_fw` 与 `aic8800_fdrv`（与 a7z 字节等价）
- `modprobe.d/aic8800.conf` MUST 含一行：`options aic_load_fw aic_fw_path=/lib/firmware/aic8800_fw/USB`（与 a7z 字节等价）

#### Scenario: usbdevice.conf 含 a7a 产品名

- **WHEN** 读取 `components/board/radxa-cubie-a7a/overlay/etc/usbdevice.conf`
- **THEN** 内容含一行 `USB_PRODUCT_NAME="radxa-cubie-a7a"`

#### Scenario: aic8800 modules-load 与 a7z 等价

- **WHEN** 比较 `components/board/radxa-cubie-a7a/overlay/etc/modules-load.d/aic8800.conf` 与 `components/board/radxa-cubie-a7z/overlay/etc/modules-load.d/aic8800.conf`
- **THEN** 两文件 sha256 一致

#### Scenario: aic8800 modprobe 与 a7z 等价

- **WHEN** 比较 `components/board/radxa-cubie-a7a/overlay/etc/modprobe.d/aic8800.conf` 与 `components/board/radxa-cubie-a7z/overlay/etc/modprobe.d/aic8800.conf`
- **THEN** 两文件 sha256 一致

#### Scenario: 实机首启 USB gadget product 名字生效

- **WHEN** 实机连主机 USB OTG 后主机 `lsusb -v` 查看
- **THEN** 描述符的 iProduct 字段含 `radxa-cubie-a7a`

### Requirement: radxa-cubie-a7a lunch target 自动生成

`flange` CLI 在不修改 `products/` 配置的前提下，MUST 自动派生以下两个 lunch target：

- `radxa-cubie-a7a-default-debug`
- `radxa-cubie-a7a-default-release`

#### Scenario: lunch 列出新板 target

- **WHEN** 执行 `flange lunch --list`
- **THEN** 输出含 `radxa-cubie-a7a-default-debug` 与 `radxa-cubie-a7a-default-release` 两项

#### Scenario: 选定 lunch target 后构建 manifest 正确

- **WHEN** 执行 `flange lunch radxa-cubie-a7a-default-debug` 后查询当前 target
- **THEN** 当前 target 为 `radxa-cubie-a7a-default-debug`
- **AND** 后续 `flange build` 调度的 board 配置为 `radxa-cubie-a7a`

### Requirement: radxa-cubie-a7a 加板不影响 a7z 产物哈希

新增 `components/board/radxa-cubie-a7a/` 目录 MUST 不影响 `radxa-cubie-a7z` 已有 lunch target 的内容哈希；`radxa-cubie-a7z-default-debug` 与 `radxa-cubie-a7z-default-release` 的 kernel / bootloader / boot / rootfs 组件 hash MUST 在本变更前后 byte-identical。

#### Scenario: a7z 增量构建零触发

- **WHEN** 在已完整构建 `radxa-cubie-a7z-default-debug` 的工作树上 apply 本变更，并再次执行 `flange build radxa-cubie-a7z-default-debug`
- **THEN** 调度器报告所有组件命中缓存（kernel / bootloader / boot / rootfs / image 均不重建）

#### Scenario: a7z 与 a7a 配置完全隔离

- **WHEN** 解析 `radxa-cubie-a7z` 与 `radxa-cubie-a7a` 的合并后配置
- **THEN** 两块板的 `kernel.dts` 不同（`sun60i-a733-cubie-a7z` vs `sun60i-a733-cubie-a7a`）
- **AND** 两块板的 `bootloader.target` 不同（`radxa-cubie-a7z` vs `radxa-cubie-a7a`）
- **AND** 两块板的 `boot.default_overlays` 不同
