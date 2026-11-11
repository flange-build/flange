# khadas-vim3l

> 阅读前提：先完成[初学指南](../first-steps.md)的环境准备，运行
> `flange target list khadas-vim3l` 确认当前目标，再按该型号硬件说明匹配介质、接口与下载模式。
> 本页是配置摘要与硬件记录；下文验收只覆盖记录的版本、产品和测试项，不代表当前全部组合已实测。
> [返回板卡索引](README.md) · [构建与刷写流程](../development-guide.md)

## 概述

Khadas VIM3L 使用 Amlogic S905D3（SM1，4×Cortex-A55、Mali-G31 MP2）。已记录 eMMC 启动、串口、以太网/SSH、蓝牙和 USB ADB；Wi-Fi 驱动与固件已加载，原始记录未证明无线关联成功。桌面、GPU、HDMI、VPU、NPU 和 SD 卡启动没有对应验收结论。官方页：<https://www.khadas.com/vim3l>。

## product / variant

与 VIM3 共用：`products: [default, desktop]`，`variants: [debug, release]`。

```
lunch khadas-vim3l-default-debug
lunch khadas-vim3l-default-release
lunch khadas-vim3l-desktop-debug
lunch khadas-vim3l-desktop-release
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
| flash 策略 | `AmlogicFlashStrategy`（pyamlboot → fastboot 两段式，详见 [amlogic 平台](../platforms/amlogic.md)） |

## eMMC 布局

BootROM 入口走 **eMMC hw boot0 分区**而非 user area，user area 只有 boot + rootfs 两块（board 关掉了 recovery）：

```
eMMC hw boot0 (4 MiB)
  └ offset 0x200  u-boot.bin.sd.bin (FIP + u-boot proper)

eMMC user area (GPT, sector size 512B)
  ├ boot     offset 0x40,    size 0x20000  (64 MiB ext4，extlinux.conf + Image + meson-sm1-khadas-vim3l.dtb)
  └ rootfs   offset 0x20040, size remaining (ext4, image_size 2G, grow_on_first_boot=True)
```

VIM3L 不交付 recovery 维护系统：首启失败直接连接 USB-C 并用 Function 键三击进 MaskROM 重刷比 adb 拉 recovery 简单，板级 `recovery.enabled = False` 关掉之后 SoC 层默认的 512MB recovery 分区也一并去掉，让位给 rootfs。env 分区也不引入：mainline u-boot 默认走 mmc raw offset 存 env，无单独分区也能工作。

## MaskROM 进入与刷写流程

VIM3L 用板上靠近 USB-C 的 Function 键进 USB Burning：

1. 连接 USB-C。
2. 在两秒内快速按 Function 键三次，然后立即松开。
3. host 端 `lsusb` 应见 `1b8e:c003`（Amlogic MaskROM）；macOS 用 `ioreg -p IOUSB -l | grep -A2 1b8e` 等价探测。
4. 跑 `flange flash` —— **无需接串口、无需手动 `fastboot usb 0`**：u-boot fragment 的 `CONFIG_PREBOOT` 检测 `${boot_source}=usb` 自动进 fastboot gadget。

host 端依赖（详见 envsetup.sh 顶部注释）：
- `pip install pyamlboot`（boot-g12.py 入口）
- `fastboot`（macOS `brew install android-platform-tools`；Linux `apt install android-tools-fastboot`）
- **libusb**（pyusb 底层）：macOS `brew install libusb`；Linux `apt install libusb-1.0-0`。缺会报 `usb.core.NoBackendError: No backend available`

完整链路：

```
host                                          board
  │ 连 USB-C，两秒内三击 Function 后松开
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

两条都不需要接串口。已经处于 fastboot 时跳过 pyamlboot；仍执行唯一设备枚举与只读握手，详见[刷写边界](../boot-and-flash.md#宿主刷写边界)。

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
- `rootfs.packages` 含 `bluez`（bluetoothd / btattach）

## 实测结果与边界

2026-05-15，commit `d4516f4`，Linux 6.12.0、Ubuntu 24.04.4 LTS arm64：

| 项目 | 已记录结果 |
| --- | --- |
| 启动 | BL2/BL31/U-Boot 到 Linux 正常，设备树 compatible 匹配 VIM3L；到 graphical.target 约 9.0 秒，仅为该镜像单次结果 |
| eMMC | Linux 枚举 mmcblk1；boot 为 64 MiB，2 GiB 初始 rootfs 首启扩容到剩余约 14.5 GiB |
| 以太网 / SSH | 接口名 end0，DHCP 与远程登录正常；普通用户 ping 曾因 capability 缺失失败 |
| Wi-Fi | BCM4359/9 固件 9.87.51.11.82 加载、wlan0 出现；当次状态 NO-CARRIER，没有关联与吞吐验收 |
| 蓝牙 | hci0 为 UP RUNNING，设备树触发 hci_uart_bcm 自动加载 BCM4359C0.hcd；不需要手动 btattach |
| Khadas MCU | IR 驱动与 red:status / white:status LED 节点出现；节点枚举不等于全部 MCU 功能测试 |

Wi-Fi 使用通用回退文件名加载板级固件；缺少 clm_blob/txcap_blob 的日志提示可能限制信道，
不能据此宣称全频段射频校准完整。仓库保留 `bluetooth-vim3l.service` 作为手动入口，
上述记录中它未启用，正常路径由内核自动绑定。

当前 USB ADB 配置由 `flange-usbgadget.conf` 加载 libcomposite，并由
`20-khadas-vim3l.yaml` 声明 gadget；已有主机枚举记录。插拔生命周期的共用约束见[USB 模式管理](../usb.md)。

## SPI（spidev）

- **来源**：`boot.overlays.board`，dtso 落 `components/board/khadas-vim3l/dtso/vim3l-spidev-spicc1.dtso`，由 device-tree-overlay 组件 `cpp + dtc` 编译；`boot.overlays.enabled` 含同一项，开机即应用
- **控制器**：SPICC1（`spi@ffd15000`，mainline `meson-g12-common.dtsi` line 2282）；spicc0 与 eMMC 共 GPIOC 不可用
- **pinmux**：引用 g12-common.dtsi 预定义 `spicc1_pins`（MOSI/MISO/CLK）+ `spicc1_ss0_pins`（native CS0），不重声明
- **默认参数**：1 路 native CS0、`spi-max-frequency = <24000000>`（24MHz，Fenix BSP 推荐稳态值；外设若需降速由 ioctl `SPI_IOC_WR_MAX_SPEED_HZ` 覆盖），模式由用户态决定
- **设备命名**：以启动后 `ls /sys/class/spi_master/` 为准，N 取决于 mainline meson-sm1.dtsi 中 `aliases { spiN = ...; }` 注册顺序；不在 dtso / 文档 写死编号。**实测 mainline 6.12 + 本 overlay**：`/sys/class/spi_master/spi0` → **`/dev/spidev0.0`**（spicc1 是 active DT 中唯一 enable 的 spi master，所以拿到 bus 0）
- **40-pin header 物理引脚**（以 mainline `drivers/pinctrl/meson/pinctrl-meson-g12a.c` 为权威）：

  | header pin | SoC pad | SPI 功能 |
  |---|---|---|
  | PIN37 | GPIOH_4 | MOSI |
  | PIN35 | GPIOH_5 | MISO |
  | PIN33 | GPIOH_7 | CLK |
  | PIN31 | GPIOH_6 | CS (native ss0) |

  注：本仓库 `components/board/khadas-vim3l/docs/vim3-sch-v12.pdf` 第 6 页 GPIO Header 区右下角的 "VIM3 SPI:" 注释把 SS/SCLK 标到 PIN33/PIN31 上是颠倒的（schematic 内部矛盾：同一 pin 既标 UARTC_TX 又标 SPIB_SS，但 mainline pinctrl 中 uart_c_tx=GPIOH_7=spi1_clk，不可能同时为 spi1_ss0=GPIOH_6）。GPIOH_6/_7 同 pad 兼具 SPI / UART_C / I²C_M1 / ISO7816 多个 alternate function，电气上 PIN31/33 这一对 pin 怎么连都对，只是软件 mux 决定它们当 SPI 用还是当 UART 用。
- **自环验证**：MOSI(PIN37) ↔ MISO(PIN35) 短接 → `spidev_test -D /dev/spidev0.0 -s 1000000 -v`（rootfs 默认不含 spidev_test，可走 Python `fcntl.ioctl(SPI_IOC_MESSAGE)` 直接打——5 行脚本，不需要装 `python3-spidev`），期望 RX 缓冲与 TX 缓冲完全一致
- **实测稳态速率（杜邦线连接）**：1 MHz / 8 MHz 完全可靠 TX==RX；**16 MHz 及以上 ioctl 返回 `ETIMEDOUT`**（mainline `drivers/spi/spi-meson-spicc.c` 等不到 transfer-done 中断），原始记录没有进一步隔离信号完整性与驱动时序原因。DT `spi-max-frequency = 24000000` 是"don't exceed"上限，每次 transfer 由用户态 `SPI_IOC_WR_MAX_SPEED_HZ` 选定实际速率；杜邦线场景下建议 ≤ 8 MHz；更高速率需按实际线长和外设重新验收
- **为什么 compatible 是 `rohm,dh2228fv`**：mainline `drivers/spi/spidev.c` 自 v5.18 起拒绝裸 `linux,spidev`（`WARN_ON: buggy DT`），社区主流借壳法 —— `rohm,dh2228fv` 是 spidev 既有 `of_match_table` 项之一，Raspberry Pi / Khadas / Armbian / Buildroot 同款做法
- **不绑定如何排查**：`dmesg | grep -i spi` 看 spicc1 与 spidev 探测顺序；`cat /sys/class/spi_master/spi*/of_node/compatible` 应为 `amlogic,meson-g12a-spicc`，其子设备 of_node compatible 应为 `rohm,dh2228fv`；更换内核时核对当前驱动的绑定方式，不能任意伪装为其他硬件型号

## 关联文档

- 平台综合页：[amlogic 平台](../platforms/amlogic.md)
