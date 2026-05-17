## ADDED Requirements

### Requirement: orangepi-cm5-tablet board 配置基础字段

`components/board/orangepi-cm5-tablet/config.py` MUST 导出 `BOARD` 字典，并在顶层声明以下字段：

- `BOARD["board"]` MUST 等于字符串 `"orangepi-cm5-tablet"`
- `BOARD["soc"]` MUST 等于字符串 `"rk3588s"`
- `BOARD["platform"]` MUST 等于字符串 `"rockchip"`
- `BOARD["kernel"]["dts"]` MUST 等于字符串 `"rk3588s-orangepi-cm5-tablet"`

board config MUST NOT 覆盖 `bootloader.branch`、`bootloader.defconfig`、`bootloader.repo`、`kernel.branch`、`kernel.repo`、`kernel.defconfig`、`partitions`、`rkbin` 任何 SoC 层字段；全部沿用 `components/platform/rockchip/rk3588s/config.py` 的 SoC 层取值。

#### Scenario: 三层合并后 board 字段正确

- **WHEN** 调用 `get_board_config("orangepi-cm5-tablet")`
- **THEN** 返回字典的 `board` 字段为 `"orangepi-cm5-tablet"`
- **AND** `soc` 字段为 `"rk3588s"`
- **AND** `platform` 字段为 `"rockchip"`
- **AND** `kernel.dts` 字段为 `"rk3588s-orangepi-cm5-tablet"`

#### Scenario: board 不覆盖 SoC bootloader 字段

- **WHEN** 调用 `get_board_config("orangepi-cm5-tablet")`
- **THEN** 返回字典的 `bootloader.branch` 等于 SoC 层 `rk3588s` 声明的分支（即 `next-dev-v2026.01`）
- **AND** `bootloader.defconfig` 等于 SoC 层 `rk3588_defconfig`（RK3588S 通用兜底）
- **AND** `rkbin.mkimage_chip` 等于 `"rk3588"`（RK3588S 与 RK3588 同 BootROM）

#### Scenario: board 不覆盖 SoC kernel 字段

- **WHEN** 调用 `get_board_config("orangepi-cm5-tablet")`
- **THEN** 返回字典的 `kernel.branch` 等于 SoC 层 `rk3588s` 声明的 `linux-6.1-stan-rkr5.1`
- **AND** `kernel.defconfig` 等于 SoC 层声明的 `["rockchip_linux_defconfig", "case_insensitive_fix.config", "rk3588_panthor.config"]` 列表

### Requirement: orangepi-cm5-tablet AP6256 WiFi/BT 链路（in-tree bcmdhd）

`components/board/orangepi-cm5-tablet/config.py` 的 `BOARD` 字典 MUST 声明 AP6256 三件套固件部署，且 MUST NOT 声明任何 OOT 驱动相关字段：

- `BOARD["kernel"]` MUST NOT 含 `oot_sources` 键
- `BOARD["kernel"]` MUST NOT 含 `+oot_modules` 键
- `BOARD["rootfs"]["+extra_firmware"]` MUST 含一条 entry，逐字段等价于 `orangepi-cm4` 同名字段：
  - `name="radxa"`
  - `repo="https://github.com/radxa-pkg/radxa-firmware"`
  - `branch="main"`
  - `repo_subdir="radxa-firmware/lib/firmware"`
  - `files` 含三项：`brcm/fw_bcm43456c5_ag.bin`、`brcm/nvram_ap6256.txt`、`brcm/BCM4345C5.hcd`
  - `dest="lib/firmware"`

AP6256 WiFi 驱动 MUST 通过 SoC 层 `kernel.defconfig` fragment 链启用的 in-tree Rockchip bcmdhd（`drivers/net/wireless/rockchip_wlan/rkwifi/bcmdhd/`）提供，board 层 MUST NOT 添加 bcmdhd 相关 fragment 或 OOT 模块。

#### Scenario: rootfs 含 AP6256 三件套固件

- **WHEN** 构建 `orangepi-cm5-tablet-default-debug` 的 rootfs 组件并 mount 产物镜像
- **THEN** `/lib/firmware/brcm/fw_bcm43456c5_ag.bin` 存在且非空
- **AND** `/lib/firmware/brcm/nvram_ap6256.txt` 存在且非空
- **AND** `/lib/firmware/brcm/BCM4345C5.hcd` 存在且非空

#### Scenario: kernel build 含 in-tree bcmdhd

- **WHEN** 构建 `orangepi-cm5-tablet-default-debug` 的 kernel 组件后检查 `.build/<target>/kernel/build/.config`
- **THEN** 含 `CONFIG_BCMDHD=y` 或 `CONFIG_BCMDHD=m`

#### Scenario: board config 不引入 OOT 链路

- **WHEN** 解析 `components/board/orangepi-cm5-tablet/config.py` 的 `BOARD` 字典
- **THEN** `BOARD["kernel"]` 不含 `oot_sources` 键
- **AND** `BOARD["kernel"]` 不含 `+oot_modules` 键

#### Scenario: 实机 WiFi 设备出现

- **WHEN** 把镜像刷入 OrangePi CM5 Tablet 实机并启动
- **THEN** `ip link` 输出含 `wlan0`

#### Scenario: 实机 BT 设备 ready

- **WHEN** 实机启动后查看 `/sys/class/bluetooth/`
- **THEN** 存在 `hci0` 或可通过 `hciattach` / `btattach` 手动绑定 UART

### Requirement: orangepi-cm5-tablet 不携带板级 dtso 与 board_overlays

`components/board/orangepi-cm5-tablet/` 目录 MUST NOT 包含 `dtso/` 子目录。`BOARD` 字典 MUST NOT 声明 `boot.board_overlays` 字段；其 `boot.{dtb_overlays,vendor_overlays,default_overlays}` 行为沿用 SoC 层 `rk3588s` 的默认值（空列表）。

Mali-G610 GPU 走 SoC 层已部署的 mainline panthor 驱动（`rk3588_panthor.config` defconfig fragment + dts 自带 `arm,mali-valhall-csf` compatible），不需要 board 层 valhall-compat dtbo 介入。

#### Scenario: board 目录无 dtso

- **WHEN** 检查 `components/board/orangepi-cm5-tablet/` 目录树
- **THEN** 不存在 `dtso/` 子目录
- **AND** 不存在任何 `.dtso` 后缀文件

#### Scenario: 三层合并后 boot.board_overlays 不存在

- **WHEN** 调用 `get_board_config("orangepi-cm5-tablet")`
- **THEN** 返回字典的 `boot` 块不含 `board_overlays` 键，或该键值为空列表 `[]`

### Requirement: orangepi-cm5-tablet 仅携带 bcmdhd 固件路径 patch

`components/board/orangepi-cm5-tablet/patches/kernel/` 目录 MUST 仅包含一份 patch `0001-bcmdhd-set-fw-ampak-path-brcm.patch`，且其内容 MUST 逐字节等价于 `components/board/orangepi-cm4/patches/kernel/0002-bcmdhd-set-fw-ampak-path-brcm.patch`。该 patch 修改 `drivers/net/wireless/rockchip_wlan/rkwifi/bcmdhd/Makefile`，启用 `-DFW_AMPAK_PATH="\"brcm\""`，让 in-tree Rockchip bcmdhd 按 `/lib/firmware/brcm/<file>` 查找 AP6256 三件套，与 `rootfs.+extra_firmware` 部署路径一致。

`patches/kernel/` MUST NOT 包含 cm4 0001（dtsi bootargs，路径不通用）或 0003（NPU disable，cm5-tablet 上必要性未验）的等价 patch。首版上电后若复现 cm4 同款问题，起独立 change 追加。

#### Scenario: board patches 目录仅含 bcmdhd patch

- **WHEN** 检查 `components/board/orangepi-cm5-tablet/patches/kernel/` 目录
- **THEN** 仅含 `0001-bcmdhd-set-fw-ampak-path-brcm.patch` 一份文件

#### Scenario: bcmdhd patch 与 cm4 0002 等价

- **WHEN** 比较 `components/board/orangepi-cm5-tablet/patches/kernel/0001-bcmdhd-set-fw-ampak-path-brcm.patch` 与 `components/board/orangepi-cm4/patches/kernel/0002-bcmdhd-set-fw-ampak-path-brcm.patch`
- **THEN** 两文件 sha256 一致

#### Scenario: 不含 cm4 风格 dtsi/NPU patch

- **WHEN** 列举 `components/board/orangepi-cm5-tablet/patches/kernel/` 下文件
- **THEN** 不存在文件名含 `bootargs`、`dtsi`、`disable-rknpu` 字样的 patch

### Requirement: orangepi-cm5-tablet overlay 文件契约

`components/board/orangepi-cm5-tablet/overlay/etc/` 目录 MUST 包含以下文件：

- `hostname` MUST 仅含一行内容 `orangepi-cm5-tablet`，末尾允许 LF

`overlay/etc/` 目录 MUST NOT 携带 `usbdevice.conf`（cm4 / rock5c-lite 也未配置；rkr5.1 generic 用户态不需要）。

#### Scenario: hostname 文件内容正确

- **WHEN** 读取 `components/board/orangepi-cm5-tablet/overlay/etc/hostname`
- **THEN** 内容为 `orangepi-cm5-tablet`（含或不含末尾 LF）

#### Scenario: overlay 不含 usbdevice.conf

- **WHEN** 检查 `components/board/orangepi-cm5-tablet/overlay/etc/` 目录
- **THEN** 不存在 `usbdevice.conf` 文件

#### Scenario: 实机首启 hostname 生效

- **WHEN** 实机首启完成后 `hostname` 命令输出
- **THEN** 输出为 `orangepi-cm5-tablet`

### Requirement: orangepi-cm5-tablet lunch target 自动生成

`flange` CLI 在不修改 `products/` 配置的前提下，MUST 自动派生以下两个 lunch target：

- `orangepi-cm5-tablet-default-debug`
- `orangepi-cm5-tablet-default-release`

#### Scenario: lunch 列出新板 target

- **WHEN** 执行 `flange lunch --list`
- **THEN** 输出含 `orangepi-cm5-tablet-default-debug` 与 `orangepi-cm5-tablet-default-release` 两项

#### Scenario: lunch 选择并 build bootloader

- **WHEN** 执行 `lunch orangepi-cm5-tablet-default-debug` 后 `flange build bootloader`
- **THEN** 命令以退出码 0 结束
- **AND** 在 `.build/<target>/bootloader/` 产物目录中生成 `idbloader.img` 与 `u-boot.itb`

### Requirement: orangepi-cm5-tablet 增量构建不影响其他 RK3588(S) 板

新增 `components/board/orangepi-cm5-tablet/` 目录 MUST 仅触发本板组件 build；现有 RK3588(S) 板（`radxa-rock5b`、`orangepi-5-plus`、`radxa-rock5c-lite`）的 bootloader / kernel / rootfs / recovery / image 组件产物 MUST 保持 byte-identical（基于内容哈希闭包计算）。

#### Scenario: rock5b bootloader 产物哈希不变

- **WHEN** 在新增 orangepi-cm5-tablet 后重新构建 `radxa-rock5b-default-debug` 的 bootloader 组件
- **THEN** 产出的 `idbloader.img` 与本变更前的产物 sha256 一致
- **AND** `u-boot.itb` sha256 一致

#### Scenario: opi5plus kernel 产物哈希不变

- **WHEN** 在新增 orangepi-cm5-tablet 后重新构建 `orangepi-5-plus-default-debug` 的 kernel 组件
- **THEN** 产出的 `Image` 与 `rk3588-orangepi-5-plus.dtb` sha256 与本变更前一致

#### Scenario: rock5c-lite rootfs 产物哈希不变

- **WHEN** 在新增 orangepi-cm5-tablet 后重新构建 `radxa-rock5c-lite-default-debug` 的 rootfs 组件
- **THEN** rootfs 产物 sha256 与本变更前一致
