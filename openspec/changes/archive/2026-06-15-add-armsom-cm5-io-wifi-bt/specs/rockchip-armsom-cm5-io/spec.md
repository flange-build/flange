## ADDED Requirements

### Requirement: armsom-cm5-io WiFi 走 rkwifibt OOT bcmdhd 并关闭内建冲突驱动

`armsom-cm5-io` 的 board config MUST 通过 `kernel.oot_sources.rkwifibt`（`https://github.com/radxa/rkwifibt.git`，`develop` 分支）声明 rkwifibt OOT 源，并以 `kernel.+oot_modules` 编出 OOT `bcmdhd.ko`（编译 `drivers/bcmdhd`，传 `CONFIG_BCMDHD=m CONFIG_BCMDHD_SDIO=y`，经 kernel kbuild `-C {kernel_src} M=.../bcmdhd modules` 机制，不依赖 bcmdhd Makefile 内硬编码 `M=$(PWD)` 的 `bcmdhd_sdio` target）。

`kernel.+defconfig` MUST 关闭两个与 OOT 驱动冲突的内建项：

- `# CONFIG_BCMDHD is not set`（内建 bcmdhd 与 OOT 模块同名 `bcmdhd`，必须关闭由 OOT 形态接管）。
- `# CONFIG_BRCMFMAC is not set`（mainline brcmfmac 与 bcmdhd 争抢 BCM43752 SDIO 设备：brcmfmac 先 bind func1、固件加载失败、`HT Avail timeout` 污染芯片状态）。

#### Scenario: OOT bcmdhd 编出且内建驱动关闭

- **WHEN** 构建 `armsom-cm5-io` kernel 组件
- **THEN** 内核 `.config` 含 `# CONFIG_BCMDHD is not set` 与 `# CONFIG_BRCMFMAC is not set`
- **AND** OOT `bcmdhd.ko` 安装到 rootfs `/lib/modules/<release>/updates/bcmdhd.ko`
- **AND** rootfs `/lib/modules/<release>/kernel/drivers/net/wireless/` 下无 `rockchip_wlan`（内建 bcmdhd）与 `brcm`（brcmfmac）目录

#### Scenario: 实机仅 OOT bcmdhd 加载、无驱动冲突

- **WHEN** 刷入镜像并首启
- **THEN** `lsmod` 含 `bcmdhd`（来自 `updates/`），不含 `brcmfmac`
- **AND** `dmesg` 不出现 `brcmfmac ... HT Avail timeout` 等冲突痕迹

### Requirement: armsom-cm5-io 部署 AP6275S 固件（含 CLM blob）

`armsom-cm5-io` 的 `rootfs.+extra_firmware` MUST 以 `source="oot:rkwifibt"`（复用 `kernel.oot_sources` 已 ensure 的 rkwifibt 源）从 `repo_subdir=firmware/broadcom/AP6275S` 部署以下文件到 rootfs `/lib/firmware/brcm/`：

- `wifi/fw_bcm43752a2_ag.bin`（SDIO WiFi 主固件）
- `wifi/nvram_ap6275s.txt`（NVRAM 校准参数）
- `wifi/clm_bcm43752a2_ag.blob`（**CLM/Country Locale Matrix——关键**：固件内置 `Generic.Min` CLM 不接受 set country，缺此 blob 则 `country setting failed -2`、无可用信道、扫不到 AP）
- `bt/BCM4362A2.hcd`（BT patchram）

#### Scenario: rootfs 镜像含 AP6275S 四件套

- **WHEN** 构建 `armsom-cm5-io` 的 rootfs 并检查产物镜像
- **THEN** `/lib/firmware/brcm/fw_bcm43752a2_ag.bin` 存在且非空
- **AND** `/lib/firmware/brcm/nvram_ap6275s.txt` 存在且非空
- **AND** `/lib/firmware/brcm/clm_bcm43752a2_ag.blob` 存在且非空
- **AND** `/lib/firmware/brcm/BCM4362A2.hcd` 存在且非空

#### Scenario: 实机 CLM 加载、country 设置成功

- **WHEN** 刷入镜像并首启，bcmdhd 加载固件
- **THEN** `dmesg` 显示 `clm_bcm43752a2_ag.blob ... open success` 与 `CLM download succeeded`
- **AND** `dmesg` 显示 `dhd_conf_set_country : Country code: CN`（而非 `country setting failed -2`）

### Requirement: armsom-cm5-io 用 modprobe.d 覆盖 OOT bcmdhd 固件路径

`components/board/armsom-cm5-io/overlay/etc/modprobe.d/bcmdhd.conf` MUST 通过 module param 把 bcmdhd 固件搜索路径覆盖到 `/lib/firmware/brcm/`：`options bcmdhd firmware_path=/lib/firmware/brcm/fw_bcmdhd.bin nvram_path=/lib/firmware/brcm/nvram.txt`。

rkwifibt OOT bcmdhd 编译默认 `CONFIG_BCMDHD_FW_PATH=/vendor/etc/firmware/`（Android 路径），与 flange 固件落点 `/lib/firmware/brcm/` 不匹配会致固件加载失败。bcmdhd 经 SDIO MODALIAS 自动 modprobe 时读本文件覆盖路径；给通用名 `fw_bcmdhd.bin`/`nvram.txt`，bcmdhd `CONFIG_BCMDHD_AUTO_SELECT` 按 chip id 拼出实际文件名命中。

#### Scenario: overlay 进 rootfs 且开机自动加载生效

- **WHEN** 构建 rootfs 并检查产物镜像
- **THEN** `/etc/modprobe.d/bcmdhd.conf` 存在且含 `options bcmdhd firmware_path=/lib/firmware/brcm/`
- **WHEN** 刷入镜像并首启（bcmdhd 经 SDIO MODALIAS 自动 modprobe）
- **THEN** `cat /sys/module/bcmdhd/parameters/firmware_path` 为 `/lib/firmware/brcm/fw_bcmdhd.bin`
- **AND** `dmesg` 显示 `Final fw_path=/lib/firmware/brcm/fw_bcm43752a2_ag.bin` 且 `open success`、`Firmware up`

#### Scenario: 实机 WiFi 扫到 AP

- **WHEN** 刷入镜像并首启
- **THEN** `ip link` 含 `wlan0`
- **AND** `nmcli dev wifi list`（或 `wpa_cli scan_results`）扫到周围至少一个 AP

### Requirement: armsom-cm5-io WiFi 芯片型号与实物对齐

`components/board/armsom-cm5-io/patches/kernel/` MUST 包含一条 patch 把 `arch/arm64/boot/dts/rockchip/rk3576-armsom-cm5.dtsi` 中 `wireless-wlan` 节点的 `wifi_chip_type` 由原型遗留的 `"rtl8852bs"` 改为 `"ap6275s"`，与实物模组 BW3752-50B1（Broadcom BCM43752）对齐。

#### Scenario: patch 落地后 dts 芯片标识为 ap6275s

- **WHEN** 在 `.build/sources/kernel/armsom-cm5-io/` 检查 `rk3576-armsom-cm5.dtsi`
- **THEN** `wireless-wlan` 节点的 `wifi_chip_type` 值为 `"ap6275s"`，不再出现 `"rtl8852bs"`
- **AND** 实机 `dmesg` 显示 `wlan_platdata_parse_dt: wifi_chip_type = ap6275s`
