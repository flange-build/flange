## MODIFIED Requirements

### Requirement: orangepi-cm4 部署 AP6256 WiFi/BT 固件

`orangepi-cm4` board 的 `BOARD["rootfs"]["+extra_firmware"]` MUST 声明从 `radxa-pkg/radxa-firmware` 仓的 `lib/firmware/` 子目录拉以下四个 AP6256（Broadcom BCM43456 / BCM4345C5 chipset）固件文件到 rootfs 的 `/lib/firmware/`：

- `brcm/brcmfmac43456-sdio.bin`（WiFi 主固件，mainline brcmfmac 按 `brcmf_fw_alloc_request()` 对 chip `BCM4345/9` 拼出的名字加载）
- `brcm/brcmfmac43456-sdio.txt`（NVRAM 校准参数，文件头 MUST 为 `#AP6256_NVRAM_*` 以确保与板载模组匹配）
- `brcm/brcmfmac43456-sdio.clm_blob`（CLM / Country Locale Matrix）
- `brcm/BCM4345C5.hcd`（Bluetooth patchram）

CLM blob MUST 部署。brcmfmac 固件内置的 Generic.Min CLM 不接受 `set country`，缺该文件会导致 `country setting failed`、无可用信道、扫不到任何 AP。

板级 MUST NOT 部署 bcmdhd 专用的 `brcm/fw_bcm43456c5_ag.bin` 与 `brcm/nvram_ap6256.txt`——这两个文件只被 Rockchip OOT bcmdhd 使用，而该驱动已在本板禁用（见「orangepi-cm4 禁用 bcmdhd 避免 SDIO 抢绑」）。

extra_firmware 条目的 `source` 字段 MUST 引用顶层 `sources` 中声明的 `radxa-firmware`，由 `SourceManager` 复用同一 checkout。

#### Scenario: rootfs 镜像含 brcmfmac 三件套与 BT patchram

- **WHEN** 构建 `orangepi-cm4-default-release` 的 rootfs 组件并 mount 产物镜像
- **THEN** `/lib/firmware/brcm/brcmfmac43456-sdio.bin` 存在且非空
- **AND** `/lib/firmware/brcm/brcmfmac43456-sdio.txt` 存在且非空
- **AND** `/lib/firmware/brcm/brcmfmac43456-sdio.clm_blob` 存在且非空
- **AND** `/lib/firmware/brcm/BCM4345C5.hcd` 存在且非空

#### Scenario: rootfs 镜像不含 bcmdhd 专用固件

- **WHEN** 构建 `orangepi-cm4-default-release` 的 rootfs 组件并 mount 产物镜像
- **THEN** `/lib/firmware/brcm/fw_bcm43456c5_ag.bin` 不存在
- **AND** `/lib/firmware/brcm/nvram_ap6256.txt` 不存在

#### Scenario: 实机首启 WiFi 接口出现

- **WHEN** 把构建出的镜像刷入实机
- **THEN** `ip link` 输出包含 `wlan0`
- **AND** `dmesg` 包含 `brcmfmac: brcmf_c_preinit_dcmds: Firmware: BCM4345/9` 类固件加载成功记录
- **AND** `dmesg` 不包含 `Direct firmware load for brcm/brcmfmac43456-sdio.bin failed` 类错误

#### Scenario: 实机 WiFi 可扫描双频 AP

- **WHEN** 在实机执行 `ip link set wlan0 up` 后扫描周边网络
- **THEN** 扫描结果同时包含 2.4GHz 频段与 5GHz 频段的 AP
- **AND** `wlan0` 的 MAC 地址不等于 NVRAM 缺省值 `00:90:4c:c5:12:38`（即已从模组 OTP 读到真实地址）

#### Scenario: 实机首启 BT HCI 接口出现

- **WHEN** 把构建出的镜像刷入实机
- **THEN** `hciconfig -a` 输出包含 `hci0`
- **AND** `dmesg` 不包含 `Failed to load Broadcom firmware file (-2)` 类错误

## ADDED Requirements

### Requirement: orangepi-cm4 禁用 bcmdhd 避免 SDIO 抢绑

`orangepi-cm4` board 的 `BOARD["kernel"]["+config"]` MUST 包含 `CONFIG_BCMDHD: 'n'`，且该设置 MUST 对所有 product / variant 生效（不得放在 `amp` 等条件分支内）。

`CONFIG_BCMDHD` 是 `drivers/net/wireless/rockchip_wlan/Kconfig` 中 `default y` 的 `bool` 型 `menuconfig`，未被任何 defconfig 显式设置，只能内建、无法编为模块，因此用户态 `modprobe` blacklist 对其无效，MUST 在 Kconfig 层关闭。

板级 MUST NOT 覆盖 `CONFIG_BRCMFMAC`——该 symbol 由 SoC 层 `rk3566` 引入的 `rockchip_linux_defconfig` 设为 `=m`，是本板期望生效的 WiFi 驱动。

两个驱动同时存在时，brcmfmac 经 SDIO MODALIAS 自动 modprobe 后先绑定 SDIO func；若其固件缺失则进入「`request_firmware` 失败 → `brcmf_sdio_htclk: HT Avail timeout` → `mmc2: card removed` → 重新枚举」的死循环，持续占住 SDIO 总线，bcmdhd 永远无法取得设备，最终两个驱动都不工作。

#### Scenario: 构建产物中不含 bcmdhd

- **WHEN** 构建 `orangepi-cm4-default-release` 的 kernel 组件
- **THEN** 生成的 `.config` 中 `CONFIG_BCMDHD` 为 `# CONFIG_BCMDHD is not set`
- **AND** `CONFIG_BRCMFMAC` 保持为 `m`

#### Scenario: 实机无 bcmdhd 且 SDIO 总线稳定

- **WHEN** 把构建出的镜像刷入实机并启动
- **THEN** `lsmod` 与 `/proc/modules` 中均无 `bcmdhd`
- **AND** `dmesg` 不包含 `brcmf_sdio_htclk: HT Avail timeout` 与反复出现的 `mmc2: card 0001 removed`

## REMOVED Requirements

### Requirement: orangepi-cm4 修复 bcmdhd 固件搜索路径

**Reason**: 该 requirement 要求板级保留一条启用 bcmdhd `FW_AMPAK_PATH="brcm"` 的 kernel patch。本 change 将该板 WiFi 驱动路线由 Rockchip OOT bcmdhd 改为 mainline brcmfmac 并设置 `CONFIG_BCMDHD=n` 后，`drivers/net/wireless/rockchip_wlan/` 整棵子树不再参与编译，patch 所修改的 `bcmdhd/Makefile` 行不再被求值，该 patch 成为孤儿代码，随本 change 一并删除。

**Migration**: 无需迁移。WiFi 固件加载路径改由 brcmfmac 的标准命名约定（`brcm/brcmfmac43456-sdio.*`）配合 `0001-dts-orangepi-cm4-bootargs-fix.patch` 提供的 `firmware_class.path=/lib/firmware` 完成，契约见「orangepi-cm4 部署 AP6256 WiFi/BT 固件」。若将来需要回退到 bcmdhd 路线，须重新提出 change，恢复该 patch 与对应的 bcmdhd 固件清单，并同时移除 `CONFIG_BCMDHD=n`。
