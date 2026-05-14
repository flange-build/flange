---
title: khadas-vim3l
type: board
status: wip
sources:
  - components/board/khadas-vim3l/config.py
  - components/board/khadas-vim3l/overlay/etc/hostname
  - components/board/khadas-vim3l/overlay/etc/systemd/system/bluetooth-vim3l.service
  - components/platform/amlogic/config.py
  - components/platform/amlogic/s905d3/config.py
  - openspec/changes/add-amlogic-khadas-vim3l/design.md
related:
  - "[[amlogic 平台]]"
  - "[[FlashStrategy 抽象]]"
  - "[[USB 线刷协议]]"
  - "[[新增板级支持]]"
updated: 2026-05-10
---

## TL;DR

Khadas VIM3L，Amlogic S905D3 SoC（SM1 family，4×Cortex-A55 @ 1.9GHz，Mali-G31 MP2），**项目首块 Amlogic 板**，同时为 amlogic 平台 + s905d3 SoC + AmlogicFlashStrategy 三件套首版验证目标。首版范围：eMMC 启动 + 串口 + GbE/SSH + AP6398S WiFi 关联 + BT scan。GPU/HDMI/VPU/NPU/USB OTG/SD 卡启动均不在范围。官方页：<https://www.khadas.com/vim3l>。

## product / variant

继承平台默认：`products: [default]`，`variants: [debug, release]`。

```
lunch khadas-vim3l-default-debug
lunch khadas-vim3l-default-release
```

## 关键差异点

| 项 | 值 |
|---|---|
| SoC | S905D3（SM1，2GB DDR4，板载 16/32GB eMMC） |
| u-boot | mainline `u-boot/u-boot @ v2024.10`，defconfig `khadas-vim3l_defconfig + flange_fastboot.config` fragment |
| kernel | mainline `torvalds/linux @ v6.12` LTS，arm64 generic `defconfig` |
| DTB | `amlogic/meson-sm1-khadas-vim3l`（`compatible = "khadas,vim3l", "amlogic,sm1"`） |
| FIP blobs | `LibreELEC/amlogic-boot-fip @ master`，**board 子目录** `khadas-vim3l/`（含 bl2/bl30/bl301/bl31/DDR fw 全套 + `aml_encrypt_g12a` 工具，SM1 复用 G12A 工具链） |
| 调试串口 | UART_AO，TTL 3.3V。**Linux 阶段 115200**（kernel args `console=ttyAML0,115200`）；BL2/BL31/u-boot proper 阶段沿用 VIM3L 硬件默认 **921600**（Khadas 官方文档值），**切到 115200 在 kernel 启动前后**，需在串口工具上对应切换波特率才能完整读到所有 banner |
| 网络 | 板载 GbE（RTL8211F PHY），eth0 |
| WiFi/BT | 板载 AP6398S 模块（BCM4359，2.4G/5G WiFi + BT5.0）；WiFi SDIO 走 mainline `brcmfmac`，BT UART 走 `hci_uart` + `btbcm` |
| flash 策略 | `AmlogicFlashStrategy`（pyamlboot → fastboot 两段式，详见 [[amlogic 平台]]） |

## eMMC 布局

BootROM 入口走 **eMMC hw boot0 分区**而非 user area，user area 只有 boot + rootfs 两块（board 关掉了 recovery）：

```
eMMC hw boot0 (4 MiB)
  └ offset 0x200  u-boot.bin.sd.bin (FIP + u-boot proper)

eMMC user area (GPT, sector size 512B)
  ├ boot     offset 0x40,    size 0x20000  (64 MiB ext4，extlinux.conf + Image + meson-sm1-khadas-vim3l.dtb)
  └ rootfs   offset 0x20040, size remaining (ext4, image_size 2G, grow_on_first_boot=True)
```

VIM3L 不交付 recovery 维护系统：首启失败直接 KEY1 + USB-C 进 MaskROM 重刷比 adb 拉 recovery 简单，板级 `recovery.enabled = False` 关掉之后 SoC 层默认的 512MB recovery 分区也一并去掉，让位给 rootfs。env 分区也不引入：mainline u-boot 默认走 mmc raw offset 存 env，无单独分区也能工作。

## MaskROM 进入与刷写流程

VIM3L 走 KEY1（板上"Function"键，靠近 USB-C）按键进 USB Burning：

1. 拔电源
2. **按住** KEY1 + 插 USB-C 上电
3. host 端 `lsusb` 应见 `1b8e:c003`（Amlogic MaskROM）；macOS 用 `ioreg -p IOUSB -l | grep -A2 1b8e` 等价探测
4. 跑 `flange flash`
5. **fastboot reboot 之前松开 KEY1**，否则板会反复回到 MaskROM

host 端依赖（详见 envsetup.sh 顶部注释）：
- `pip install pyamlboot`（boot-g12.py 入口）
- `fastboot`（macOS `brew install android-platform-tools`；Linux `apt install android-tools-fastboot`）
- **libusb**（pyusb 底层）：macOS `brew install libusb`；Linux `apt install libusb-1.0-0`。缺会报 `usb.core.NoBackendError: No backend available`

完整链路：

```
host                                          board
  │ 按住 KEY1 + 插 USB-C 上电
  │                                       ──▶ MaskROM (1b8e:c003)
  │ flange flash all khadas-vim3l-default-debug
  │   ├─ pyamlboot 推 u-boot.bin 到 SoC DDR
  │   │                                   ──▶ BL2 (SRAM) → BL31 → u-boot proper (DDR)
  │   ├─ u-boot 自动进 fastboot gadget
  │   ├─ fastboot flash bootloader → eMMC hw boot0 offset 0x200
  │   ├─ fastboot flash boot       → GPT boot 分区
  │   ├─ fastboot flash rootfs     → GPT rootfs 分区
  │   └─ fastboot reboot
  │ 用户松开 KEY1
  │                                       ──▶ BootROM 从 hw boot0 起 BL2 → 启动到 systemd
```

host 端依赖：`pip install pyamlboot` + `apt install android-tools-fastboot`。

## WiFi / BT

板载 AP6398S 是 Broadcom BCM4359 WiFi + BT5.0 combo 模块（SDIO + UART）。驱动全部走 mainline in-tree，三件套固件全部从 Khadas fenix 板级版拉：

| 源文件（fenix） | 落地路径 | 用途 |
|---|---|---|
| `brcmfmac4359-sdio_ap6398s.bin` | `/lib/firmware/brcm/brcmfmac4359-sdio.bin` | WiFi 固件（brcmfmac 主固件加载名）|
| `brcmfmac4359-sdio_ap6398s.txt` | `/lib/firmware/brcm/brcmfmac4359-sdio.txt` | NVRAM（brcmfmac fallback 通用名）|
| `BCM4359C0_ap6398s.hcd` | `/lib/firmware/brcm/BCM4359C0.hcd` | BT patchram（btbcm 标准名）|

fenix 仓库内路径：`archives/hwpacks/wlan-firmware/brcm/`。三件套由 board 层 `rootfs.+extra_firmware` 单一 entry 一并声明（独立 clone 到 `.build/sources/extra-firmware/khadas-fenix-ap6398s/`）。

**为何全部走 fenix（不用 apt 包）**：Ubuntu 24.04 没有 Debian 风格的 `firmware-brcm80211` 切片包（Ubuntu 把 brcm 固件打在 monolithic `linux-firmware` 内，整包 ~500MB 不适合 embedded 默认拉）。fenix 反而提供完整三件套且全是 Khadas 为 VIM3L 上实际 BCM4359 模组的板级 RF 校准版，比通用 firmware 更精准。

**为何取 fenix `_ap6398s` 后缀版**：AP6398S 是 VIM3L 实际板上的 combo 模块，板级 RF 校准与 patchram 由 Khadas 维护，通用版可能首启可用但 RF 性能不达标。

## 板私有 overlay

- `overlay/etc/hostname` — 设备主机名 `khadas-vim3l`
- `overlay/etc/systemd/system/bluetooth-vim3l.service` — `btattach -B /dev/ttyAML6 -P bcm`，`Before=bluetooth.target`，把 BT UART 注册为 HCI 设备（mainline `hci_uart` + `btbcm` 走 patchram 流程）
- `+extra_packages: [bluez]`（含 bluetoothd / btattach；wireless-tools / iw 已在 base 默认）

## 已知问题 / 实测笔记

实板验证尚未完成（首版 OpenSpec change `add-amlogic-khadas-vim3l` 仍在实施中），以下待实板回填：

- TODO 启动时间（BL2 → systemd login prompt）
- TODO WiFi 关联首次是否直接可用（`iw wlan0 scan` BSS 数）
- TODO BT scan 首次是否直接可用（`bluetoothctl scan on`）
- TODO 若 BT 失败 / WiFi 通过：触发 design Decision 6 fallback，BT 拆出后续变更，首版仅交付 WiFi（验收降级）

## 关联文档

- 提案与设计：`openspec/changes/add-amlogic-khadas-vim3l/{proposal,design,tasks}.md`
- 平台综合页：[[amlogic 平台]]（amlogic 平台首板，同时为新平台 + 新 SoC + 新 FlashStrategy 三件套）
