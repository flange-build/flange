## Why

flange 已有 Amlogic 平台与 Khadas VIM3L（S905D3/SM1）首板支持，但尚未覆盖
Radxa Zero 1.5 这类 S905Y2/G12A 小型板。用户已有 Radxa Zero 1.5（8GB eMMC、
AW-CM256SM Wi-Fi/BT、TTL 串口）并以 macOS 作为刷写宿主机，需要把现有 Amlogic
链路扩展到该设备，形成可刷写、可启动、Wi-Fi/BT 可用的板级支持。

## What Changes

- 新增 Amlogic `s905y2` SoC 配置，复用现有 `amlogic` 平台构建策略、mainline
  U-Boot、mainline Linux 6.12 LTS 与 LibreELEC `amlogic-boot-fip` FIP 打包链路。
- 新增 `radxa-zero` board 配置，目标硬件为 Radxa Zero 1.5、8GB eMMC、
  AW-CM256SM Wi-Fi/BT 模组。
- 新增 Radxa Zero 专用 bootloader 配置组合：`radxa-zero_defconfig` 叠加
  fastboot fragment，并通过 `amlogic-boot-fip/radxa-zero/` 的 board 级 blob
  集合生成 Amlogic 可启动镜像。
- 新增 Radxa Zero kernel/boot/rootfs/image 配置：`kernel.dts` 使用
  `meson-g12a-radxa-zero`，boot console 使用 `ttyAML0`，首版关闭 recovery，
  仅刷写 `bootloader` / `boot` / `rootfs`。
- 新增 AW-CM256SM Wi-Fi/BT 固件部署约定：rootfs 必须包含 CYW43455/BCM43455
  系列 brcmfmac Wi-Fi 固件、板级 NVRAM 与 Bluetooth patchram，并验证
  `iw wlan0 scan` 与 `bluetoothctl scan on`。
- 扩展 Amlogic macOS host 刷写验收：确认 `fastboot`、`boot-g12.py`、`pyusb`
  与 `libusb` 可用，MaskROM `1b8e:c003` 可被 macOS USB 栈探测。
- 新增 Radxa Zero 板级 wiki/文档，记录串口、MaskROM、刷写、eMMC 布局、
  Wi-Fi/BT 验收与排障。

## Capabilities

### New Capabilities

（无。Radxa Zero 是现有 `amlogic-platform` 与 `amlogic-flash` 的扩展，不新增
独立 capability。）

### Modified Capabilities

- `amlogic-platform`: 增加 `s905y2` SoC、`radxa-zero` board、AW-CM256SM
  Wi-Fi/BT 固件部署、关闭 recovery 的 eMMC 8GB Radxa Zero 首版验收需求。
- `amlogic-flash`: 增加 Radxa Zero 在 macOS host 上通过 MaskROM →
  `boot-g12.py` → fastboot 完成 eMMC 刷写的验收场景。

## Impact

- **代码层**：
  - 预期主要新增配置与测试；若现有 Amlogic 抽象不足，仅在平台策略内做
    配置化泛化，不改框架层。
  - 可能新增或复用 `components/platform/amlogic/s905y2/patches/bootloader/`
    下的 fastboot fragment，需确认 eMMC 对应 `CONFIG_FASTBOOT_FLASH_MMC_DEV`。
- **内容层**：
  - `components/platform/amlogic/s905y2/config.py`
  - `components/board/radxa-zero/config.py`
  - `components/board/radxa-zero/overlay/etc/{hostname,usbdevice.conf}`
  - 必要时新增 Radxa Zero/AW-CM256SM 固件声明或板级 overlay。
- **外部依赖**：
  - `u-boot/u-boot @ v2024.10` 或后续 mainline 标签，需包含
    `radxa-zero_defconfig`。
  - `torvalds/linux @ v6.12` 或后续 6.12.y 标签，需包含
    `meson-g12a-radxa-zero.dts`。
  - `LibreELEC/amlogic-boot-fip`，需包含 `radxa-zero/` FIP blob 与
    `aml_encrypt_g12a`。
  - AW-CM256SM/CYW43455 固件来源需在实施前核实并固定。
- **host 端依赖**：
  - macOS 上的 `fastboot`、`boot-g12.py`、Python `pyusb`、`libusb`。
- **非目标**：
  - 不支持无 eMMC 的 Radxa Zero SKU。
  - 不支持 SD 卡启动。
  - 不启用 recovery。
  - 不把 HDMI/GPU/VPU/音频/GPIO header overlay 纳入首版验收。
  - 不重构配置继承、engine、flash 框架层。
