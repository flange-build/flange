---
title: atk-rk3506b
type: board
status: stable
sources:
  - components/board/atk-rk3506b/config.jsonnet
  - components/board/atk-rk3506b/patches/bootloader/0001-add-alientek-rk3506-board.patch
  - components/board/atk-rk3506b/patches/bootloader/0002-fix-vendor-fit-bootdev.patch
  - components/board/atk-rk3506b/patches/kernel/0001-reserve-amp-firmware-memory.patch
  - components/board/atk-rk3506b/patches/kernel/0002-enable-gud-fbcon-console.patch
  - components/board/atk-rk3506b/patches/kernel/0003-align-yt8512c-bsp-init.patch
  - components/board/atk-rk3506b/patches/kernel/0004-disable-spi0-for-fluxion-pwm.patch
  - components/board/atk-rk3506b/patches/kernel/0005-claim-pwm1-clocks-for-fluxion-amp.patch
  - components/board/atk-rk3506b/patches/kernel/0006-release-i2c1-for-fluxion-as5600.patch
  - components/board/atk-rk3506b/patches/rtl8733bu/0001-disable-removed-regulatory-flag.patch
  - components/platform/rockchip/rk3506b/config.jsonnet
  - builder/platforms/rockchip/amp.py
  - docs/boards/atk-rk3506b.md
  - components/app/cardputer_music_player/app.yaml
  - components/packages/cardputer-all-in-one/README.md
  - openspec/specs/rockchip-atk-rk3506b/spec.md
  - openspec/specs/cardputer-music-player/spec.md
  - openspec/changes/archive/2026-07-18-add-cardputer-music-player/evidence/cardputer-music-player-hardware.md
  - openspec/changes/archive/2026-07-15-add-rk3506b-atk-rk3506b/evidence/rk3506b-hardware-acceptance.md
  - openspec/changes/archive/2026-07-15-align-rk3506b-yt8512c-init/evidence/rk3506b-yt8512c-hardware.md
  - openspec/changes/archive/2026-07-14-add-atk-rk3506b-rtl8733bu-wifi-bt/evidence/rtl8733bu-acceptance.md
  - openspec/changes/add-rk3506-fluxion-foc-amp/
related:
  - "[[rockchip 平台]]"
  - "[[amp 构建器]]"
  - "[[AMP 协处理器与 rpmsg]]"
  - "[[FlashStrategy 抽象]]"
  - "[[rk3506 AMP UART4 RPMsg demo]]"
  - "[[Cardputer USB 复合设备]]"
  - "[[Cardputer 在线音乐播放器]]"
updated: 2026-08-24
---

## TL;DR

正点原子 ATK-RK3506B：512 MiB DDR + 512 MiB SPI NAND，flange 首块 ARM32、
UBI/UBIFS、vendor FIT Rockchip 板。Linux 占 CPU0-1，CPU2 跑最小 RT-Thread；
板载 RTL8733BUUA 通过 USB Hub 同时提供 WiFi 与 Bluetooth，UART4 AMP 保持独立。
双路 YT8512C 100M Ethernet 与 USB1 Host 的 Cardputer GUD/fbcon、HID 键盘、
UAC1 扬声器/麦克风均已实机验收。

## 配置

| 项 | 值 |
|---|---|
| kernel | `linux-6.1-stan-rkr5.1`，ARM `zImage`，gcc-10.3.1 |
| DTS | `rk3506b-alientek-mipi720x1280-nand-ubi-ubifs-amp-linux` |
| boot | `boot.img` vendor FIT；启动参数取 DTS `chosen.bootargs` |
| rootfs | Ubuntu Base 24.04 armhf，`rootfs.ubi`，`ubi0:rootfs` |
| AMP | CPU2 `0x03e00000`，UART4 1500000 8N1，RPMsg `0x3003` |
| Ethernet | 2× YT8512C，RMII1，PHY ID `0x00000128`，各自在独立 MDIO bus 的 address 1 |
| WiFi | RTL8733BUUA，USB `0bda:b733` `ff/ff/ff`，OOT `8733bu.ko` |
| Bluetooth | RTL8733BUUA，USB `0bda:b733` `e0/01/01`，OOT `rtk_btusb.ko` |
| Cardputer | USB `16d0:10a9`，GUD + HID + mono 16 kHz UAC1；官方网易云在线播放器自启 |

分区顺序固定为 `idbloader → uboot → boot → recovery(1 MiB 占位) → amp → rootfs`，
因此 rootfs 始终是 `mtd5`。SPI NAND 不生成 GPT `raw.img`；构建期由配置生成
`parameter.txt`，刷写走 `UL -noreset`、`DI -p` 与具名 `DI`，不调用该 loader
不支持的 `SSD`。

## 双路 YT8512C 有线网

### 硬件与时钟契约

两路 PHY 原理图完全对称，均为 YT8512C。`RXDV` 与 `CLK_CTL` strap 都上拉，
即 `{RXDV, CLK_CTL}=11b`，选择 RMII1 模式；PHY 的 `TXC/RMII_REF_CLK` 是
50 MHz input，由 SoC GMAC 输出。因此 DTS 从 MAC 视角使用
`clock_in_out = "output"` 是正确配置，不能为了消除 clock warning 改成 `input`。
两颗 PHY 的 PHY address 都是 1，但分别位于独立 MDIO bus，不存在地址冲突。

### 排除过程与根因

故障版本中两路 GMAC 都能 probe，MDIO 也能读取 `0x00000128`，但插入网线没有
carrier。构建 DTB、运行时 FDT 与可工作的 ATK BSP 对比后，GMAC/MDIO、reset、
pinctrl、50 MHz clock 和 PHY node 均一致；最终 Ethernet Kconfig 也已逐项对齐。
所以问题不在 DTS、clock tree 或 driver 是否编入，而在当前精简版 Motorcomm driver
为 ID `0x00000128` 执行的初始化流程。

与 BSP 对比确认三项直接差异：

1. `0x00000128` 与旧 ID `0x00000118` 共用 `yt8512_clk_init()`，会额外改写
   `0x0050`/`0x4000`，并在末尾发出不等待完成的 software reset；紧随其后的
   LED/auto-sleep MDIO 访问存在 reset 时序竞争。板级硬件已经由 strap 固定 RMII1，
   不需要这段覆盖。
2. LED1 helper 把 enable bit `0x0010` 误当作扩展寄存器地址；正确的 LED1
   control register 是 `0x40c3`。这是独立存在的确定性寄存器错误。
3. 关闭 auto-sleep 后缺少 BSP 的最终 software reset，PHY driver entry 也没有
   soft-reset callback。排障时执行一次 `mii-tool -R` 曾短暂产生
   `10Mbps/Full Link Up`，进一步证明物理链路存在而初始化/reset 顺序有误。

板级 patch 为 `0x00000128` 建立独立流程：

1. 写 LED0 `0x40c0`；
2. 写 LED1 `0x40c3`；
3. 清除 `0x2027` bit 15，关闭 auto-sleep；
4. 调用 `genphy_soft_reset()`，等待 reset bit 清除并传播 MDIO 错误。

driver entry 同时补充 `.soft_reset = genphy_soft_reset`，使 config_init 前后的两次
reset 都受完成轮询保护。旧 ID `0x00000118` 保留原 clock init；Linux 6.1 在没有
PHY IRQ callback 时会自行选择 polling，因此不能照抄 BSP 的
`.flags = PHY_POLL`（`PHY_POLL` 是值为 `-1` 的 IRQ sentinel，不是 driver flag）。

### 实机验收与诊断

新 `boot.img` 冷启动后的两路 MDIO device 均为 `0x00000128`，绑定
`YT8512B Ethernet (irq=POLL)`。先接 `end0`、拔出并改接 `end1`，内核依次记录：

```text
end0: Link is Up - 100Mbps/Full - flow control off
end0: Link is Down
end1: Link is Up - 100Mbps/Full - flow control off
```

最终 `end1` 为 `carrier=1, speed=100, duplex=full`，`end0` 在未接线时为
`carrier=0`。整个验收没有执行 `mii-tool -R` 或其他手工 MDIO reset。

```bash
# 确认两路 PHY ID 与 driver
for node in /sys/bus/mdio_bus/devices/stmmac-{0,1}:01; do
    cat "$node/phy_id"
    readlink "$node/driver"
done

# 查看 carrier、协商状态和 Link Up/Down
for netdev in end0 end1; do
    echo "$netdev carrier=$(cat /sys/class/net/$netdev/carrier)"
    ethtool "$netdev"
done
dmesg | grep -Ei 'stmmac|YT8512|Link is'
```

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
- Cardputer 的 `gud`、`usbhid`、`snd-usb-audio` 已自动绑定；TTY、键盘、扬声器和麦克风均通过。
- `cardputer_music_player` armhf 包已由板级 rootfs 安装，编译依赖按 App 声明动态进入 Docker；
  默认二维码登录后加载 32 首红心曲目，列表异步就绪，服务 `NRestarts=0`。
- 双路 YT8512C 均绑定 PHY ID `0x00000128`；`end0`/`end1` 分别接线时均以
  100 Mbps/Full 建链，拔线产生 Link Down，不依赖手工 PHY reset。
- UART4/MSH console 与 RPMsg 多轮 binary echo 已通过；2.4/5 GHz 连接、Bluetooth HCI
  与 ADB 长时间回归尚未独立验收。
- 原 42 个 pytest 旧契约失败均已修复且未删测试；Python 3.12 全量为
  `1485 passed`、OpenSpec strict 为 `64 passed, 0 failed`，归档证据和回滚资料已复核。

## fluxion product（2026-08-24）

板级现有 `default`、`fluxion` 两个 product。`default` 继续使用已上板验证的 `rk3506_amp_uart4_rtt_demo`，作为启动与 RPMsg echo 救援基线；`fluxion` 改用仓库外 App `fluxion_runtime`，默认 checkout 布局为 `../fluxion/Device/FlangeApps/fluxion_runtime`，不会把开发机绝对路径写进配置。

CPU2 需要独占的硬件资源由板级 patch 明确交接：0004 禁用 Linux SPI0，释放 GPIO0_C0/C3 给 PWM U 相与栅驱 EN；0005 让 `rockchip_amp` 持有 PWM1 时钟，避免 `clk_disable_unused` 关断输出；0006 禁用空置的 Linux I2C1，把 GPIO1_B1/B2、I2C1 时钟和 AS5600 所需的 GIC INTID 73 路由交给 CPU2。commit `878963ab` 补齐了 IRQ 73 的 CPU2 路由。

Docker 完整镜像构建已经通过，`bootloader`、`boot`、`amp`、`rootfs`、`flash-config.json` 和 `mtd-bundle.json` 产物闭环已确认。真实功率级接线、无功率级 RPMsg/遥测、硬件 break、快环 WCET/抖动以及 HIL 故障注入仍是待完成的实机门禁，不能把“构建通过”写成“整机验收通过”。
