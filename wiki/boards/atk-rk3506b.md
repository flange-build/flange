---
title: atk-rk3506b
type: board
status: stable
sources:
  - components/board/atk-rk3506b/config.py
  - components/board/atk-rk3506b/patches/bootloader/0001-add-alientek-rk3506-board.patch
  - components/board/atk-rk3506b/patches/bootloader/0002-fix-vendor-fit-bootdev.patch
  - components/board/atk-rk3506b/patches/kernel/0001-reserve-amp-firmware-memory.patch
  - components/board/atk-rk3506b/patches/rtl8733bu/0001-disable-removed-regulatory-flag.patch
  - components/platform/rockchip/rk3506b/config.py
  - docs/boards/atk-rk3506b.md
  - openspec/changes/add-rk3506b-atk-rk3506b/evidence/rk3506b-hardware-acceptance.md
  - openspec/changes/archive/2026-07-14-add-atk-rk3506b-rtl8733bu-wifi-bt/evidence/rtl8733bu-acceptance.md
related:
  - "[[rockchip 平台]]"
  - "[[amp 构建器]]"
  - "[[AMP 协处理器与 rpmsg]]"
  - "[[FlashStrategy 抽象]]"
  - "[[rk3506 AMP UART4 RPMsg demo]]"
updated: 2026-07-14
---

## TL;DR

正点原子 ATK-RK3506B：512 MiB DDR + 512 MiB SPI NAND，flange 首块 ARM32、
UBI/UBIFS、vendor FIT Rockchip 板。Linux 占 CPU0-1，CPU2 跑最小 RT-Thread；
板载 RTL8733BUUA 通过 USB Hub 同时提供 WiFi 与 Bluetooth，UART4 AMP 保持独立。

## 配置

| 项 | 值 |
|---|---|
| kernel | `linux-6.1-stan-rkr5.1`，ARM `zImage`，gcc-10.3.1 |
| DTS | `rk3506b-alientek-mipi720x1280-nand-ubi-ubifs-amp-linux` |
| boot | `boot.img` vendor FIT；启动参数取 DTS `chosen.bootargs` |
| rootfs | Ubuntu Base 24.04 armhf，`rootfs.ubi`，`ubi0:rootfs` |
| AMP | CPU2 `0x03e00000`，UART4 1500000 8N1，RPMsg `0x3003` |
| WiFi | RTL8733BUUA，USB `0bda:b733` `ff/ff/ff`，OOT `8733bu.ko` |
| Bluetooth | RTL8733BUUA，USB `0bda:b733` `e0/01/01`，OOT `rtk_btusb.ko` |

分区顺序固定为 `idbloader → uboot → boot → recovery(1 MiB 占位) → amp → rootfs`，
因此 rootfs 始终是 `mtd5`。SPI NAND 不生成 GPT `raw.img`；构建期由配置生成
`parameter.txt`，刷写走 `UL -noreset`、`DI -p` 与具名 `DI`，不调用该 loader
不支持的 `SSD`。

## RTL8733BUUA WiFi/蓝牙

### 硬件路由

| 层级 | 连接 | Linux 枚举 |
|---|---|---|
| SoC | USB2 OTG1 `USB20_OTG1_DP/DM`，host mode | `dwc2 ff780000.usb` / bus 2 |
| Hub | CH334R 上行接 OTG1，下行 port 3 接 RTL8733BUUA | `1a86:8091` |
| WiFi/BT | U10 `USB_DP/USB_DM` 接 `HUB_DP3/HUB_DM3` | `0bda:b733` composite device |
| WiFi interface | vendor class | `2-1.3:1.2`，`ff/ff/ff` |
| Bluetooth interface | Wireless Controller class | `2-1.3:1.0/1.1`，`e0/01/01` |

`CHIP_EN` 由 3.3 V 经 10 kΩ 电阻上拉；原理图未连接 SDIO、UART、PCM 或 wake GPIO。
现有 DTB 已能枚举 Hub 与 `0bda:b733`，因此不增加 WiFi/BT DTS patch，也不修改
MMC、UART5、GMAC1、USB gadget OTG0 或 UART4 AMP。

### 软件栈

- 当前 `linux-6.1-stan-rkr5.1` 缺少 RTL8733BU WiFi source，使用固定的
  `wirenboard/rtl8733bu@2d9048be60759206b8db5e2370420333ef0b8478` 构建 OOT
  `8733bu.ko`。USB table 精确匹配 `0bda:b733` 的 `ff/ff/ff` interface，WiFi
  firmware 已编入 module。构建参数关闭 driver/proc debug，并沿用官方 BSP 的
  两项 GCC warning suppression，适配启用 `CONFIG_WERROR` 的 kernel build。
  公开基线还引用当前内核已移除的 regulatory flag，因此用一行 OOT source
  兼容补丁按官方 SDK 的相同方式禁用该赋值；这不是 DTS patch，不改变硬件路由。
- Bluetooth 使用固定的
  `fengyuzhong/rtl8733bu-bt@dc7b30b4b9d2c5437a80bfaff6c8a77c97642778`
  构建 OOT `rtk_btusb.ko`；关闭 in-tree `btusb`，避免竞争同一 interface。
- 通用 cfg80211/BT/rfkill core 保留；`WL_ROCKCHIP`、`RFKILL_RK`、BCMDHD、
  HCI UART 均关闭，不加载与 USB topology 无关的 SDIO/GPIO platform glue。
- rootfs 只增加 `bluez`，NetworkManager 与 wpa_supplicant 复用基础包集合。
- Bluetooth driver 与 firmware 同源，只安装 `/lib/firmware/rtl8733bu_fw` 和
  `/lib/firmware/rtl8733bu_config`；不安装完整 `linux-firmware` 或 Broadcom firmware。

### 使用与排障

```bash
# USB topology 与 driver binding
lsusb
cat /sys/bus/usb/devices/2-1.3/uevent
for node in /sys/bus/usb/devices/2-1.3:*; do
    echo "$node: $(readlink "$node/driver")"
done
lsmod | grep -E '8733bu|rtk_btusb'

# WiFi scan 与连接
ip -brief link
nmcli radio wifi on
nmcli device wifi list --rescan yes
nmcli device wifi connect '<SSID>' password '<密码>'

# Bluetooth controller 与扫描
systemctl status bluetooth --no-pager
bluetoothctl list
bluetoothctl power on
bluetoothctl --timeout 15 scan on

# Driver 与 firmware 诊断
modinfo 8733bu | grep -E 'filename|alias|version'
modinfo rtk_btusb | grep -E 'filename|alias'
dmesg | grep -Ei '8733|rtk_btusb|bluetooth|hci|firmware|usb 2-1.3'
ls -l /lib/firmware/rtl8733bu_*
```

若 `lsusb` 没有 `1a86:8091` 或 `0bda:b733`，先查 OTG1 host/PHY 与 Hub 供电；
若 USB device 存在但没有 WLAN，检查 `2-1.3:1.2` driver symlink、`8733bu.ko`
和 `modules.alias`；若 WiFi 正常但没有 HCI controller，检查 `1.0/1.1` 是否绑定
`rtk_btusb`、两份 firmware request 与 BlueZ log。OTG1 host (`ff780000`) 与 ADB
gadget OTG0 (`ff740000`) 是两个 controller，不应互相切换 role。

## 实机状态（2026-07-14）

- `flange flash` 从 Maskrom 全刷成功，断电后进入 Linux 6.1.115；`/` 为可写 UBIFS。
- `/sys/devices/system/cpu/online` 为 `0-1`；`/proc/iomem` 排除
  `0x03b00000-0x03efffff`，不会覆盖 AMP 共享区与 CPU2 firmware。
- RPMsg channel 已枚举；USB gadget 自动加载 module 并绑定 `ff740000.usb`，ADB 可直接进入。
- USB2 OTG1 已枚举 CH334R `1a86:8091` 与 RTL8733BUUA `0bda:b733`；刷入本次镜像后
  WLAN interface 已正常出现，证明 USB WiFi driver 的枚举、自动加载与注册链路可用。
- UART4/MSH console 与 RPMsg 多轮 binary echo 已通过；2.4/5 GHz 连接、Bluetooth HCI
  与 GMAC/ADB 完整回归尚未独立验收。
