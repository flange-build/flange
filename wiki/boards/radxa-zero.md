---
title: radxa-zero
type: board
status: wip
sources:
  - components/board/radxa-zero/config.py
  - components/board/radxa-zero/overlay/etc/hostname
  - components/board/radxa-zero/overlay/etc/usbdevice.conf
  - components/board/radxa-zero/overlay/etc/modules-load.d/flange-usbgadget.conf
  - components/platform/amlogic/config.py
  - components/platform/amlogic/s905y2/config.py
  - components/platform/amlogic/s905y2/patches/bootloader/flange_fastboot.config
  - openspec/changes/add-s905y2-radxa-zero/design.md
related:
  - "[[amlogic 平台]]"
  - "[[khadas-vim3l]]"
  - "[[FlashStrategy 抽象]]"
  - "[[新增板级支持]]"
updated: 2026-05-29
---

## TL;DR

Radxa Zero 1.5，Amlogic S905Y2 SoC（G12A family，4×Cortex-A53，Mali-G31），**项目第二块 Amlogic 板**，复用 amlogic 平台 + AmlogicFlashStrategy，新增 `s905y2` SoC 层。首版范围：8GB eMMC 启动 + 串口 + ADB/SSH + AW-CM256SM WiFi scan + BT scan。GPU/HDMI/VPU/SD 卡启动/recovery 均不在范围。host 为 macOS。官方页：<https://radxa.com/products/zeros/zero>。**实板验收待完成**（构建配置已就绪，未上板）。

## product / variant

```
lunch radxa-zero-default-debug
lunch radxa-zero-default-release
```

## 关键差异点（vs khadas-vim3l）

| 项 | 值 |
|---|---|
| SoC | S905Y2（G12A，板载 8GB eMMC） |
| u-boot | mainline `@ v2024.10`，defconfig `radxa-zero_defconfig + flange_fastboot.config`（base 仅 DFU_RAM，fastboot 由 fragment 叠加） |
| kernel | mainline `@ v6.12` LTS，arm64 generic `defconfig` |
| DTB | `amlogic/meson-g12a-radxa-zero`（`compatible = "radxa,zero","amlogic,g12a"`） |
| FIP blobs | `LibreELEC/amlogic-boot-fip @ master`，board 子目录 `radxa-zero/`（bl2/bl30/bl301/bl31 + DDR fw + `aml_encrypt_g12a`，Makefile `include ../g12a.inc`） |
| 调试串口 | UART_AO，TTL 3.3V，`console=ttyAML0,115200`（DTS `serial0=&uart_AO`, `stdout-path serial0:115200n8`） |
| WiFi/BT | 板载 AW-CM256SM（AzureWave，Cypress CYW43455）；WiFi SDIO（sd_emmc_a）走 `brcmfmac`；BT UART_A 走 serdev `btbcm`，**mainline DTS 自动绑定** |
| flash 策略 | `AmlogicFlashStrategy`（pyamlboot → fastboot 两段式，详见 [[amlogic 平台]]） |

## eMMC 布局

BootROM 走 eMMC hw boot0 而非 user area；user area 仅 boot + rootfs（关 recovery）：

```
eMMC hw boot0       └ u-boot.bin.sd.bin（FIP + u-boot proper）
eMMC user area (GPT, 512B sector)
  ├ boot    offset 0x40,    size 0x20000  (64 MiB ext4，extlinux.conf + Image + dtb)
  └ rootfs  offset 0x20040, size remaining (ext4, image_size 2G, grow_on_first_boot)
```

`recovery.enabled=False`：首启失败用 MaskROM 重刷比 adb 拉 recovery 简单，省 512MB 给 rootfs。

## MaskROM 进入与刷写流程

Radxa Zero 进 MaskROM：拔电 → **按住板上 USB boot 键（BOOT/FN，靠 USB-C OTG 口）** + 插靠内侧 USB-C 上电 → host 见 `1b8e:c003`（macOS：`ioreg -p IOUSB -l | grep -A2 1b8e`）。

```
host                                board
 按住 BOOT + 插 USB-C 上电      ──▶ MaskROM (1b8e:c003)
 flange flash
   ├ boot-g12.py 推 u-boot.bin(裸FIP) 到 DDR ──▶ BL2→BL31→u-boot proper
   │                                            board_late_init setenv boot_source=usb
   │                                            PREBOOT 检 usb → 自动 fastboot usb 0
   ├ fastboot oem format        → mmc2 GPT 按实际 8GB 容量重建
   ├ fastboot flash bootloader  → eMMC hw boot0
   ├ fastboot flash boot/rootfs → user area GPT
   └ fastboot reboot           ──▶ 冷启动 boot_source=emmc → extlinux → Linux 6.12
```

整条链路无需接串口手动 `fastboot usb 0`（fragment PREBOOT 自动进 fastboot）。重刷快路径同 [[khadas-vim3l]]（`fastboot reboot bootloader` 或 `adb reboot bootloader`）。

host 端依赖（macOS，已预检通过）：`pip install pyamlboot`（boot-g12.py）+ `brew install android-platform-tools libusb` + `python3 -c "import usb"`。

## WiFi / BT 固件

AW-CM256SM（CYW43455）三件套 + BT patchram 从权威 `radxa-pkg/radxa-firmware @ main`（`radxa-firmware/lib/firmware/`）拉，落地 rename 成 mainline 通用名：

| 源文件（radxa-firmware） | 落地 `/lib/firmware/brcm/` | 用途 |
|---|---|---|
| `cypress/cyfmac43455-sdio.bin` | `brcmfmac43455-sdio.bin` | WiFi 固件 |
| `brcm/nvram_azw256.txt` | `brcmfmac43455-sdio.txt` | NVRAM（azw256 = AzureWave AW-CM256SM 专用） |
| `cypress/cyfmac43455-sdio.clm_blob` | `brcmfmac43455-sdio.clm_blob` | CLM 校准 |
| `brcm/BCM4345C0.hcd` | `BCM4345C0.hcd` | BT patchram（CYW43455 BT core） |

由 board 层 `rootfs.+extra_firmware` 单一 entry 声明（独立 clone 到 `.build/sources/extra-firmware/radxa-zero-aw-cm256sm/`）。不用 monolithic `linux-firmware`（~500MB 不适合 embedded）。

**BT 无 btattach 单元**：mainline `meson-g12a-radxa-zero.dts` 在 `&uart_A` 直接声明 `bluetooth { compatible="brcm,bcm43438-bt"; shutdown-gpios=...; }` serdev 子节点，内核 `hci_serdev`/`btbcm` 自动 probe + 加载 patchram（与 VIM3L 需 btattach 不同）。

## 板私有 overlay

- `overlay/etc/hostname` → `radxa-zero`
- `overlay/etc/usbdevice.conf` → adbd USB gadget（VID 0x18d1 AOSP，PRODUCT/GROUP `radxa-zero`）
- `overlay/etc/modules-load.d/flange-usbgadget.conf` → `libcomposite`（mainline 6.12 模块化，adbd 依赖）
- `+packages: [bluez]`

## 排障 / 待实板确认项

- **eMMC mmc dev 编号**：fragment `CONFIG_FASTBOOT_FLASH_MMC_DEV=2` 依 G12A `sd_emmc_c=eMMC` 标准拓扑设定；首刷前串口进 u-boot 跑 `mmc list` 确认实际枚举编号，不符则改 fragment（task 1.6）。
- **WiFi 固件请求路径**：`dmesg | grep brcmfmac` 确认实际请求名；若驱动按 dts compatible 找 `brcmfmac43455-sdio.radxa,zero.txt` 优先，可加 symlink 精调。
- **distro/extlinux**：`radxa-zero_defconfig` 与 `khadas-vim3l_defconfig` 同样未显式开 BOOTSTD（依 meson/Kconfig 默认）；VIM3L 实证可走 extlinux，预期 Radxa Zero 同栈，待上板确认。
- **BT 自动绑定**：若 serdev 未起，`dmesg | grep -i hci` 排查，fallback 才考虑加 btattach 单元。

## 关联文档

- 提案与设计：`openspec/changes/add-s905y2-radxa-zero/{proposal,design,tasks}.md`
- 平台综合页：[[amlogic 平台]]；同代 SM1 板 [[khadas-vim3l]]（btattach / clm 等经验可参考）
