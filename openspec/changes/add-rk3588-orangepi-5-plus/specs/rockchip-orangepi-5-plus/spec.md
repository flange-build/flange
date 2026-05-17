## ADDED Requirements

### Requirement: orangepi-5-plus board 配置基础字段

`components/board/orangepi-5-plus/config.py` MUST 导出 `BOARD` 字典，并在顶层声明以下字段：

- `BOARD["board"]` MUST 等于字符串 `"orangepi-5-plus"`
- `BOARD["soc"]` MUST 等于字符串 `"rk3588"`
- `BOARD["platform"]` MUST 等于字符串 `"rockchip"`
- `BOARD["kernel"]["dts"]` MUST 等于字符串 `"rk3588-orangepi-5-plus"`

board config MUST NOT 覆盖 `bootloader.branch`、`bootloader.defconfig`、`bootloader.repo`、`kernel.branch`、`kernel.repo`、`kernel.defconfig`、`partitions`、`rkbin` 任何 SoC 层字段；全部沿用 `components/platform/rockchip/rk3588/config.py` 的 SoC 层取值。

#### Scenario: 三层合并后 board 字段正确

- **WHEN** 调用 `get_board_config("orangepi-5-plus")`
- **THEN** 返回字典的 `board` 字段为 `"orangepi-5-plus"`
- **AND** `soc` 字段为 `"rk3588"`
- **AND** `platform` 字段为 `"rockchip"`
- **AND** `kernel.dts` 字段为 `"rk3588-orangepi-5-plus"`

#### Scenario: board 不覆盖 SoC bootloader 字段

- **WHEN** 调用 `get_board_config("orangepi-5-plus")`
- **THEN** 返回字典的 `bootloader.branch` 等于 SoC 层 `rk3588` 声明的分支（即 `next-dev-v2026.01`）
- **AND** `bootloader.defconfig` 等于 SoC 层 `rk3588_defconfig`
- **AND** `rkbin.mkimage_chip` 等于 `"rk3588"`

#### Scenario: board 不覆盖 SoC kernel 字段

- **WHEN** 调用 `get_board_config("orangepi-5-plus")`
- **THEN** 返回字典的 `kernel.branch` 等于 SoC 层 `rk3588` 声明的 `linux-6.1-stan-rkr5.1`
- **AND** `kernel.defconfig` 等于 SoC 层声明的 `["rockchip_linux_defconfig", "case_insensitive_fix.config", "rk3588_panthor.config"]` 列表

### Requirement: orangepi-5-plus M.2 E-key RTL8852BE WiFi/BT 链路

`components/board/orangepi-5-plus/config.py` 的 `BOARD` 字典 MUST 声明 RTL8852BE OOT 驱动与固件链路，逐字段等价于 `radxa-rock5b` 的同名字段：

- `BOARD["kernel"]["oot_sources"]["rkwifibt"]` MUST 含 `repo="https://github.com/radxa/rkwifibt.git"` 与 `branch="develop"`
- `BOARD["kernel"]["+oot_modules"]` MUST 含一条 entry：`dir="{rkwifibt_src}/drivers/rtl8852be"`、`make_args` 含 `ARCH=arm64`、`CROSS_COMPILE=aarch64-linux-gnu-`、`KSRC={kernel_src}`、`M={rkwifibt_src}/drivers/rtl8852be`，`ko_pattern` 含 `{rkwifibt_src}/drivers/rtl8852be/8852be.ko`
- `BOARD["rootfs"]["+extra_firmware"]` MUST 含一条 entry：`name="rkwifibt-rtl8852be"`、`source="oot:rkwifibt"`、`repo_subdir="firmware/realtek/RTL8852BE"`、`files=[{src:rtl8852bu_fw,dest:rtl8852bu_fw.bin},{src:rtl8852bu_config,dest:rtl8852bu_config.bin}]`、`dest="lib/firmware/rtl_bt"`

#### Scenario: kernel build 产出 8852be.ko

- **WHEN** 构建 `orangepi-5-plus-default-debug` 的 kernel 组件
- **THEN** modules 产物中含 `8852be.ko`

#### Scenario: rootfs 含 RTL8852BE BT firmware

- **WHEN** 构建 `orangepi-5-plus-default-debug` 的 rootfs 组件并 mount 产物镜像
- **THEN** `/lib/firmware/rtl_bt/rtl8852bu_fw.bin` 存在且非空
- **AND** `/lib/firmware/rtl_bt/rtl8852bu_config.bin` 存在且非空

#### Scenario: 实机 WiFi/BT 设备出现

- **WHEN** 把镜像刷入 OrangePi 5 Plus 实机并插入 RTL8852BE M.2 E-key 卡
- **THEN** `ip link` 输出含 `wlan0`
- **AND** `hciconfig -a` 输出含 `hci0`

### Requirement: orangepi-5-plus 不携带板级 dtso 与 board_overlays

`components/board/orangepi-5-plus/` 目录 MUST NOT 包含 `dtso/` 子目录。`BOARD` 字典 MUST NOT 声明 `boot.board_overlays` 字段；其 `boot.{dtb_overlays,vendor_overlays,default_overlays}` 行为沿用 SoC 层 `rk3588` 的默认值（空列表）。

Mali-G610 GPU 走 SoC 层已部署的 mainline panthor 驱动（`rk3588_panthor.config` defconfig fragment + dts 自带 `arm,mali-valhall-csf` compatible），不需要 board 层 valhall-compat dtbo 介入。

#### Scenario: board 目录无 dtso

- **WHEN** 检查 `components/board/orangepi-5-plus/` 目录树
- **THEN** 不存在 `dtso/` 子目录
- **AND** 不存在任何 `.dtso` 后缀文件

#### Scenario: 三层合并后 boot.board_overlays 不存在

- **WHEN** 调用 `get_board_config("orangepi-5-plus")`
- **THEN** 返回字典的 `boot` 块不含 `board_overlays` 键，或该键值为空列表 `[]`

### Requirement: orangepi-5-plus overlay 文件契约

`components/board/orangepi-5-plus/overlay/etc/` 目录 MUST 包含以下文件：

- `hostname` MUST 仅含一行内容 `orangepi-5-plus`，末尾允许 LF
- `usbdevice.conf` MUST 与 `components/board/radxa-rock5b/overlay/etc/usbdevice.conf` 内容等价（同 USB Gadget VID/PID/serial 格式约定）

#### Scenario: hostname 文件内容正确

- **WHEN** 读取 `components/board/orangepi-5-plus/overlay/etc/hostname`
- **THEN** 内容为 `orangepi-5-plus`（含或不含末尾 LF）

#### Scenario: 实机首启 hostname 生效

- **WHEN** 实机首启完成后 `hostname` 命令输出
- **THEN** 输出为 `orangepi-5-plus`

### Requirement: orangepi-5-plus lunch target 自动生成

`flange` CLI 在不修改 `products/` 配置的前提下，MUST 自动派生以下两个 lunch target：

- `orangepi-5-plus-default-debug`
- `orangepi-5-plus-default-release`

#### Scenario: lunch 列出新板 target

- **WHEN** 执行 `flange lunch --list`
- **THEN** 输出含 `orangepi-5-plus-default-debug` 与 `orangepi-5-plus-default-release` 两项

#### Scenario: lunch 选择并 build bootloader

- **WHEN** 执行 `lunch orangepi-5-plus-default-debug` 后 `flange build bootloader`
- **THEN** 命令以退出码 0 结束
- **AND** 在 `.build/<target>/bootloader/` 产物目录中生成 `idbloader.img` 与 `u-boot.itb`

### Requirement: orangepi-5-plus 增量构建不影响其他 RK3588 板

新增 `components/board/orangepi-5-plus/` 目录 MUST 仅触发本板组件 build；现有 RK3588 板（`radxa-rock5b`）的 bootloader / kernel / rootfs / recovery / image 组件产物 MUST 保持 byte-identical（基于内容哈希闭包计算）。

#### Scenario: rock5b bootloader 产物哈希不变

- **WHEN** 在新增 orangepi-5-plus 后重新构建 `radxa-rock5b-default-debug` 的 bootloader 组件
- **THEN** 产出的 `idbloader.img` 与本变更前的产物 sha256 一致
- **AND** `u-boot.itb` sha256 一致

#### Scenario: rock5b kernel 产物哈希不变

- **WHEN** 在新增 orangepi-5-plus 后重新构建 `radxa-rock5b-default-debug` 的 kernel 组件
- **THEN** 产出的 `Image` 与 `rk3588-rock-5b.dtb` sha256 与本变更前一致
- **AND** `8852be.ko` 模块 sha256 与本变更前一致
