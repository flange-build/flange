---
title: khadas-vim3l
type: board
status: wip
sources:
  - components/board/khadas-vim3l/config.jsonnet
  - components/board/khadas-vim3l/dtso/vim3l-spidev-spicc1.dtso
  - components/board/khadas-vim3l/overlay/etc/hostname
  - components/board/khadas-vim3l/overlay/etc/systemd/system/bluetooth-vim3l.service
  - components/platform/amlogic/config.jsonnet
  - components/platform/amlogic/s905d3/config.jsonnet
  - openspec/changes/add-amlogic-khadas-vim3l/design.md
  - openspec/changes/vim3l-enable-spidev/design.md
related:
  - "[[amlogic 平台]]"
  - "[[FlashStrategy 抽象]]"
  - "[[USB 线刷协议]]"
  - "[[新增板级支持]]"
updated: 2026-05-15
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
4. 跑 `flange flash` —— **无需接串口、无需手动 `fastboot usb 0`**：u-boot fragment 的 `CONFIG_PREBOOT` 检测 `${boot_source}=usb` 自动进 fastboot gadget
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
  │ flange flash
  │   ├─ pyamlboot 推 u-boot.bin (FIP) 到 DDR
  │   │                                   ──▶ BL2 (SRAM) → BL31 → u-boot proper (DDR)
  │   │                                       u-boot board_late_init setenv boot_source=usb
  │   │                                       PREBOOT 检 boot_source=usb → 自动 fastboot usb 0
  │   ├─ host 等 fastboot device 出现
  │   ├─ fastboot oem format        → mmc2 GPT 重建（按实际 14.6 GiB 容量）
  │   ├─ fastboot flash bootloader  → eMMC hw boot0 (mmc2 boot0) offset 0x200
  │   ├─ fastboot flash boot        → GPT boot 分区
  │   ├─ fastboot flash rootfs      → GPT rootfs 分区
  │   └─ fastboot reboot
  │ 用户松开 KEY1
  │                                       ──▶ 冷启动 BootROM 从 hw boot0 起 BL2 → u-boot
  │                                           board_late_init setenv boot_source=emmc
  │                                           PREBOOT 不触发 fastboot → Distroboot →
  │                                           extlinux.conf → Linux 6.12
```

### 重刷工作流（板已刷过 u-boot 到 eMMC）

不用每次断电按 KEY1 重进 MaskROM。两条快路径：

**A. 板在 Linux**：

```bash
# host 端
adb reboot bootloader     # 走 adb 协议；板冷启动 → u-boot 读 reboot reason → 进 fastboot
flange flash              # detect_device 看到 fastboot device，跳过 pyamlboot
```

**B. 板已在 fastboot 模式**（上一轮刷完后用 `fastboot reboot bootloader` 等留下）：

```bash
flange flash              # 直接进 flash 分区流程（连 pyamlboot 都不跑）
```

两条都不需要接串口。`AmlogicFlashStrategy.pre_flash` 看到 `device.mode == "fastboot"` 立即 return，省 sudo 提示 + ~3s pyamlboot 推送等待。

host 端依赖：`pip install pyamlboot` + `apt install android-tools-fastboot`。

## WiFi / BT

板载 AP6398S 是 Broadcom BCM4359 WiFi + BT5.0 combo 模块（SDIO + UART）。驱动全部走 mainline in-tree，三件套固件全部从 Khadas fenix 板级版拉：

| 源文件（fenix） | 落地路径 | 用途 |
|---|---|---|
| `brcmfmac4359-sdio_ap6398s.bin` | `/lib/firmware/brcm/brcmfmac4359-sdio.bin` | WiFi 固件（brcmfmac 主固件加载名）|
| `brcmfmac4359-sdio_ap6398s.txt` | `/lib/firmware/brcm/brcmfmac4359-sdio.txt` | NVRAM（brcmfmac fallback 通用名）|
| `BCM4359C0_ap6398s.hcd` | `/lib/firmware/brcm/BCM4359C0.hcd` | BT patchram（btbcm 标准名）|

fenix 仓库内路径：`archives/hwpacks/wlan-firmware/brcm/`。三件套由 board 层 `rootfs.extra_firmware` 单一 entry 通过 canonical source 引用声明。

**为何全部走 fenix（不用 apt 包）**：Ubuntu 24.04 没有 Debian 风格的 `firmware-brcm80211` 切片包（Ubuntu 把 brcm 固件打在 monolithic `linux-firmware` 内，整包 ~500MB 不适合 embedded 默认拉）。fenix 反而提供完整三件套且全是 Khadas 为 VIM3L 上实际 BCM4359 模组的板级 RF 校准版，比通用 firmware 更精准。

**为何取 fenix `_ap6398s` 后缀版**：AP6398S 是 VIM3L 实际板上的 combo 模块，板级 RF 校准与 patchram 由 Khadas 维护，通用版可能首启可用但 RF 性能不达标。

## 板私有 overlay

- `overlay/etc/hostname` — 设备主机名 `khadas-vim3l`
- `overlay/etc/systemd/system/bluetooth-vim3l.service` — `btattach -B /dev/ttyAML6 -P bcm`，`Before=bluetooth.target`，把 BT UART 注册为 HCI 设备（mainline `hci_uart` + `btbcm` 走 patchram 流程）
- `+extra_packages: [bluez]`（含 bluetoothd / btattach）

## 实测结果（首版 add-amlogic-khadas-vim3l 落地验证）

实测日期：2026-05-15。构建版本：commit `d4516f4`。kernel：`6.12.0`。OS：Ubuntu 24.04.4 LTS arm64。

### 启动链路 ✓
- BL2 / BL31 / u-boot 串口：921600；kernel 起来后切：115200
- `systemd-analyze`：内核 1.483s + 用户态 7.552s = **9.036s 到 graphical.target**
- `cat /proc/device-tree/compatible` → `khadas,vim3l` + `amlogic,sm1` ✓

### 存储 ✓
- eMMC 在 Linux 是 `mmcblk1`（mmcblk0 是 mmc0 SDIO，eMMC 在 mmc2 但 Linux 按 probe 顺序编号 1）
- `mmcblk1` 14.6 GiB user area + `mmcblk1boot0` / `mmcblk1boot1` 各 4 MiB hw partition ✓
- 分区：`mmcblk1p1` 64 MiB boot（ext4 LABEL=boot 挂 `/boot`）+ `mmcblk1p2` 14.5 GiB rootfs
- **rootfs `grow_on_first_boot` 工作**：`image_size: 2G` 初始 → 实占 13G（`df -h /` 报 15G / 用 784M）✓

### 网络 ✓
- 主线 6.12 默认 predictable ifname：`end0`（不是 eth0）；MAC `c8:63:14:70:cc:7a`，状态 UP / LOWER_UP
- DHCP 拿到 IP（实测 172.17.1.157）+ SSH 服务 `active`，远程登录成功
- 用户态 `ping` 因 cap_net_raw 缺失报错（普通 user 没 setuid bit，无关）

### WiFi ✓（带小 nit）
- driver bind：`brcmfmac mmc2:0001:1` → chip BCM4359/9 ✓
- firmware：`/lib/firmware/brcm/brcmfmac4359-sdio.{bin,txt}` + `BCM4359C0.hcd` 三件套（fenix `_ap6398s` 板级版）全部落位
- 加载版本：`Firmware: BCM4359/9 wl0: version 9.87.51.11.82 (Feb 22 2022)`
- `wlan0` 接口 UP（NO-CARRIER 待关联）；MAC `18:93:7f:66:bb:76`
- **小 nit 1**：brcmfmac 优先找板级文件名 `brcmfmac4359-sdio.khadas,vim3l.bin` 不存在（fenix 给的是 `_ap6398s` 后缀），fallback 到通用 `brcmfmac4359-sdio.bin` 加载成功 —— 工作但少了"以 dts compatible 字符串为后缀"的板级精调路径；可后续做 file rename / symlink 优化
- **小 nit 2**：`clm_blob` / `txcap_blob` 缺失，brcmfmac warning `device may have limited channels available` —— 不致命，RF 国家代码 calibration 不完整可能限制 5GHz 信道；后续可补 fenix 的 clm_blob
- **小 nit 3**：base 包没装 `iw` 工具，`iw dev` not found —— 用 `wpa_supplicant` / `nmcli` 仍能关联；建议后续加 `iw` 到 platform `+packages`

### BT ✓✓ **比预期还好 —— 完全自动工作**
- `hci0` UP RUNNING，BD `18:93:7F:66:BB:77`（WiFi MAC + 1，combo 模块标准行为），Type Primary Bus UART
- HCI 5.0 / BCM4359 chip id 121 / Firmware Manufacturer Broadcom ✓
- **mainline 6.12 + `meson-khadas-vim3.dtsi` 在 `&uart_A` 节点直接声明 `bluetooth { compatible = "brcm,bcm43438-bt" }`**，`hci_uart_bcm` driver 自动 probe → btbcm 自动加载 `/lib/firmware/brcm/BCM4359C0.hcd` patchram 完成 init
- **`bluetooth-vim3l.service` 是多余的**：我们手写的 btattach systemd 单元当前 `disabled / inactive`，dts auto-attach 不需要 userspace 协助。**后续优化可移除该 service**（design Decision 6 的 fallback 矩阵无需触发）
- 板上的两颗 warning（`vbat not found, using dummy regulator` / `vddio not found`）—— 用 dummy regulator 兜底，BT 功能不受影响

### Khadas MCU（间接证据 ✓）
- `Registered IR keymap rc-khadas` 出现在 dmesg —— MCU IR remote driver 已注册
- `/sys/class/leds/` 暴露 `red:status` / `white:status` 两颗板载 LED —— `gpio-khadas-mcu` 子驱动 bind 成功
- i2c-adapter sysfs 路径与早期 schema 不同（mainline 改了 sysfs 拓扑），但 MCU 功能可见

### Non-Goal 验证（确认这些是预期不工作的）
- GPU (Mali-G31) / HDMI / VPU (amvdec) / NPU / USB OTG gadget / SD 卡启动模式：未配置，预期不可用 ✓

## 已落地的体验改进

- ✓ **flange flash 全自动**：u-boot `CONFIG_PREBOOT` 检测 `${boot_source}=usb` 自动进 fastboot；host 端 `AmlogicFlashStrategy.detect_device` 把 fastboot 模式也算"设备就绪"，`pre_flash` 看到 fastboot 直接跳过 pyamlboot。首次 MaskROM 刷入与后续重刷都**无需接串口**，无需手动 `fastboot usb 0`。详见 commits `fc8aa3c` + `576636e`。
- ✓ **adbd 通过 USB gadget 暴露**：board overlay 加 `/etc/modules-load.d/flange-usbgadget.conf` 自动 `modprobe libcomposite`（mainline 6.12 模块化），加板级 `/etc/usbdevice.conf`（USB_VENDOR_ID=0x18d1 Google AOSP / USB_PRODUCT_NAME=khadas-vim3l）。host 端 `adb devices` 直接见。详见 commit `<待 commit>`。

## SPI（spidev）

- **来源**：`boot.overlays.board`，dtso 落 `components/board/khadas-vim3l/dtso/vim3l-spidev-spicc1.dtso`，由 device-tree-overlay 组件 `cpp + dtc` 编译；`boot.overlays.enabled` 含同一项，开机即应用
- **控制器**：SPICC1（`spi@ffd15000`，mainline `meson-g12-common.dtsi` line 2282）；spicc0 与 eMMC 共 GPIOC 不可用，详见 `openspec/changes/vim3l-enable-spidev/design.md` 决策 1
- **pinmux**：引用 g12-common.dtsi 预定义 `spicc1_pins`（MOSI/MISO/CLK）+ `spicc1_ss0_pins`（native CS0），不重声明
- **默认参数**：1 路 native CS0、`spi-max-frequency = <24000000>`（24MHz，Fenix BSP 推荐稳态值；外设若需降速由 ioctl `SPI_IOC_WR_MAX_SPEED_HZ` 覆盖），模式由用户态决定
- **设备命名**：以启动后 `ls /sys/class/spi_master/` 为准，N 取决于 mainline meson-sm1.dtsi 中 `aliases { spiN = ...; }` 注册顺序；不在 dtso / wiki 写死编号。**实测 mainline 6.12 + 本 overlay**：`/sys/class/spi_master/spi0` → **`/dev/spidev0.0`**（spicc1 是 active DT 中唯一 enable 的 spi master，所以拿到 bus 0）
- **40-pin header 物理引脚**（以 mainline `drivers/pinctrl/meson/pinctrl-meson-g12a.c` 为权威）：

  | header pin | SoC pad | SPI 功能 |
  |---|---|---|
  | PIN37 | GPIOH_4 | MOSI |
  | PIN35 | GPIOH_5 | MISO |
  | PIN33 | GPIOH_7 | CLK |
  | PIN31 | GPIOH_6 | CS (native ss0) |

  注：本仓库 `components/board/khadas-vim3l/docs/vim3-sch-v12.pdf` 第 6 页 GPIO Header 区右下角的 "VIM3 SPI:" 注释把 SS/SCLK 标到 PIN33/PIN31 上是颠倒的（schematic 内部矛盾：同一 pin 既标 UARTC_TX 又标 SPIB_SS，但 mainline pinctrl 中 uart_c_tx=GPIOH_7=spi1_clk，不可能同时为 spi1_ss0=GPIOH_6）。GPIOH_6/_7 同 pad 兼具 SPI / UART_C / I²C_M1 / ISO7816 多个 alternate function，电气上 PIN31/33 这一对 pin 怎么连都对，只是软件 mux 决定它们当 SPI 用还是当 UART 用。
- **自环验证**：MOSI(PIN37) ↔ MISO(PIN35) 短接 → `spidev_test -D /dev/spidev0.0 -s 1000000 -v`（rootfs 默认不含 spidev_test，可走 Python `fcntl.ioctl(SPI_IOC_MESSAGE)` 直接打——5 行脚本，不需要装 `python3-spidev`），期望 RX 缓冲与 TX 缓冲完全一致
- **实测稳态速率（杜邦线连接）**：1 MHz / 8 MHz 完全可靠 TX==RX；**16 MHz 及以上 ioctl 返回 `ETIMEDOUT`**（mainline `drivers/spi/spi-meson-spicc.c` 等不到 transfer-done 中断），这是杜邦线物理层 SI + meson_spicc 驱动 burst 边界的已知现象，与 dtso 无关。DT `spi-max-frequency = 24000000` 是"don't exceed"上限，每次 transfer 由用户态 `SPI_IOC_WR_MAX_SPEED_HZ` 选定实际速率；杜邦线场景下建议 ≤ 8 MHz，焊接走线场景可向上探
- **为什么 compatible 是 `rohm,dh2228fv`**：mainline `drivers/spi/spidev.c` 自 v5.18 起拒绝裸 `linux,spidev`（`WARN_ON: buggy DT`），社区主流借壳法 —— `rohm,dh2228fv` 是 spidev 既有 `of_match_table` 项之一，Raspberry Pi / Khadas / Armbian / Buildroot 同款做法。完整论证见 `openspec/changes/vim3l-enable-spidev/design.md` 决策 2
- **不绑定如何排查**：`dmesg | grep -i spi` 看 spicc1 与 spidev 探测顺序；`cat /sys/class/spi_master/spi*/of_node/compatible` 应为 `amlogic,meson-g12a-spicc`，其子设备 of_node compatible 应为 `rohm,dh2228fv`；若上游某天进一步收紧借壳法，切换路径是改 dtso 内 compatible 到 `of_match_table` 中另一既有项（`lineartechnology,ltc2488` / `ge,achc` / `semtech,sx1301` 等任选）

## 后续优化项（不阻塞首版交付）

- 移除 `overlay/etc/systemd/system/bluetooth-vim3l.service`（dts auto-attach 已 cover）
- 把 `iw` 加进 platform `+packages`（VIM3L base 包没 iw，影响 WiFi 调试体感）
- 补 fenix `clm_blob`（如有）让 RF 国家代码 calibration 完整
- WiFi NVRAM 文件命名 align 到 brcmfmac 的 dts-compatible-suffix 优先级（`brcmfmac4359-sdio.khadas,vim3l.bin` symlink）

## 关联文档

- 提案与设计：`openspec/changes/add-amlogic-khadas-vim3l/{proposal,design,tasks}.md`
- 平台综合页：[[amlogic 平台]]（amlogic 平台首板，同时为新平台 + 新 SoC + 新 FlashStrategy 三件套）
