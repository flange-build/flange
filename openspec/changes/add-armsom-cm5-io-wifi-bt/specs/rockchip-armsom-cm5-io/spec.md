## ADDED Requirements

### Requirement: armsom-cm5-io 部署 BCM43752 / AP6275S WiFi/BT 固件

`armsom-cm5-io` board 的 `BOARD["rootfs"]["+extra_firmware"]` MUST 声明从 `radxa-pkg/radxa-firmware` 仓的 `lib/firmware/` 子目录（`repo_subdir = "radxa-firmware/lib/firmware"`）拉以下三个 BCM43752 / AP6275S（Broadcom BCM43752 chipset，BT 子系统标识 BCM4362A2）固件文件到 rootfs 的 `/lib/firmware/`：

- `brcm/fw_bcm43752a2_ag.bin`（SDIO WiFi 主固件，Rockchip bcmdhd `CONFIG_BCMDHD_AUTO_SELECT` 走 chip-id 拼名后实际加载文件）
- `brcm/nvram_ap6275s.txt`（NVRAM 校准参数）
- `brcm/BCM4362A2.hcd`（Bluetooth patchram）

extra_firmware 条目的 `source` 字段 MUST 缺省（即 `"repo"`），由 `SourceManager.ensure_extra_firmware` 独立 clone 到 `.build/sources/extra-firmware/` 下；`dest` MUST 为 `"lib/firmware"`。

#### Scenario: rootfs 镜像含 BCM43752 三件套

- **WHEN** 构建 `armsom-cm5-io-default-release` 的 rootfs 组件并 mount 产物镜像
- **THEN** `/lib/firmware/brcm/fw_bcm43752a2_ag.bin` 存在且非空
- **AND** `/lib/firmware/brcm/nvram_ap6275s.txt` 存在且非空
- **AND** `/lib/firmware/brcm/BCM4362A2.hcd` 存在且非空

#### Scenario: 实机首启 WiFi 接口出现并可扫描

- **WHEN** 把构建出的镜像刷入实机并启动
- **THEN** `ip link` 输出包含 `wlan0`
- **AND** `iw dev wlan0 scan` 能扫到周围至少一个 AP
- **AND** `dmesg` 不包含 `Direct firmware load for /brcm/fw_bcm43752a2_ag.bin failed` 类错误（缺 `brcm/` 前缀的失败路径）

#### Scenario: BT 固件就绪可手动拉起 hci0

- **WHEN** 把构建出的镜像刷入实机并启动
- **THEN** `/lib/firmware/brcm/BCM4362A2.hcd` 在 rootfs 中就绪
- **AND** 经用户态加载 patchram（产品方自取 BT 用户态栈）后 `hciconfig -a` 可出现 `hci0`，`dmesg` 不出现 `Failed to load Broadcom firmware file (-2)` 类错误

### Requirement: armsom-cm5-io 修复 bcmdhd 固件搜索路径

`components/board/armsom-cm5-io/patches/kernel/` MUST 包含一条 patch 启用 Rockchip bcmdhd 驱动的 `FW_AMPAK_PATH="brcm"`，修改 `drivers/net/wireless/rockchip_wlan/rkwifi/bcmdhd/Makefile` 中 `DHDCFLAGS += -DFW_AMPAK_PATH="\"...\""` 对应行（取消默认注释并把路径设为 `brcm`），内容与 `orangepi-cm4` / `tspi-rk3566` 的同名 bcmdhd patch 等价。

未应用该 patch 时，bcmdhd 拼出的固件名缺 `brcm/` 前缀（如 `/fw_bcm43752a2_ag.bin`），即使固件文件正确部署也会因路径不匹配而 `request_firmware` 失败。

#### Scenario: patch 落地后 bcmdhd 加载固件路径正确

- **WHEN** kernel 构建期应用该 patch 并在实机加载 bcmdhd 模块
- **THEN** `drivers/net/wireless/rockchip_wlan/rkwifi/bcmdhd/Makefile` 中 `FW_AMPAK_PATH` 已取消注释且值为 `brcm`
- **AND** 实机 `dmesg` 不出现 bcmdhd 从缺 `brcm/` 前缀路径加载固件失败的错误

### Requirement: armsom-cm5-io WiFi 芯片型号与实物对齐

`components/board/armsom-cm5-io/patches/kernel/` MUST 包含一条 patch 把 `arch/arm64/boot/dts/rockchip/rk3576-armsom-cm5.dtsi` 中 `wireless-wlan` 节点的 `wifi_chip_type` 由原型遗留的 `"rtl8852bs"` 改为 `"ap6275s"`，与实物模组 BW3752-50B1（Broadcom BCM43752）对齐。

该树 `drivers/net/wireless/rockchip_wlan/` 仅含 `rkwifi`(bcmdhd)、无 RTL8852BS 源码，原 `rtl8852bs` 标识既无对应驱动也与实物不符。

#### Scenario: patch 落地后 dts 芯片标识为 ap6275s

- **WHEN** 在 `.build/sources/kernel/armsom-cm5-io/` 检查 `arch/arm64/boot/dts/rockchip/rk3576-armsom-cm5.dtsi`
- **THEN** `wireless-wlan` 节点的 `wifi_chip_type` 值为 `"ap6275s"`
- **AND** 不再出现 `wifi_chip_type = "rtl8852bs"`
