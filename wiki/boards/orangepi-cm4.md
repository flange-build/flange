---
title: orangepi-cm4
type: board
status: stable
sources:
  - components/board/orangepi-cm4/config.jsonnet
  - components/board/orangepi-cm4/patches/kernel/0001-dts-orangepi-cm4-bootargs-fix.patch
  - components/board/orangepi-cm4/patches/kernel/0003-dts-orangepi-cm4-disable-rknpu.patch
  - components/board/orangepi-cm4/patches/kernel/0004-add-orangepi-cm4-amp-dts.patch
  - components/board/orangepi-cm4/docs/amp.md
  - components/board/orangepi-cm4/overlay/etc/hostname
  - components/board/orangepi-cm4/overlay/etc/usbdevice.conf
  - components/board/orangepi-cm4/overlay/etc/systemd/system/bluetooth-orangepi-cm4.service
  - components/board/orangepi-cm4/overlay/usr/lib/flange/bt-unblock.sh
  - docs/first-steps.md
related:
  - "[[rockchip 平台]]"
  - "[[amp 构建器]]"
  - "[[AMP 协处理器与 rpmsg]]"
  - "[[lunch-build-flash 流程]]"
  - "[[新增板级支持]]"
updated: 2026-09-05
---

> 阅读前提：先完成[初学指南](../../docs/first-steps.md)的环境准备，运行
> `flange target list orangepi-cm4` 确认当前目标，再按该型号硬件说明匹配介质、接口与下载模式。
> 本页是配置摘要与硬件记录；下文验收只覆盖记录的版本、产品和测试项，不代表当前全部组合已实测。
> [返回板卡索引](index.md) · [构建与刷写流程](../workflows/lunch-build-flash-流程.md)

## TL;DR

Orange Pi CM4，RK3566 计算模块。当前交付范围：**无屏可启动 + AP6256 WiFi/BT 即插即用**，禁用不可用 NPU，并提供可选 `amp` / `amp-rtt` product。DSI 屏适配（实机用 Waveshare CM4-DISP-BASE-5A）尚未交付，单独立项推进。

## product / variant

板级声明：`products: [default, amp, amp-rtt]`，`variants: [debug, release]`。

```
lunch orangepi-cm4-default-debug
lunch orangepi-cm4-default-release
lunch orangepi-cm4-amp-debug
lunch orangepi-cm4-amp-release
lunch orangepi-cm4-amp-rtt-debug
lunch orangepi-cm4-amp-rtt-release
```

## 关键差异点

| 项 | 值 |
|---|---|
| DTB | default 用 `rk3566-orangepi-cm4-base`（保持空壳）；AMP products 用 `rk3566-orangepi-cm4-amp` |
| board overlay | 无（dsi1 维持 dtsi 默认 disabled） |
| kernel patches | `0001` bootargs、`0003` disable rknpu、`0004` AMP dts |
| kernel config | `CONFIG_BCMDHD=n`（关掉与 brcmfmac 抢 SDIO 的 OOT 驱动，全 product/variant 生效） |
| rootfs packages | `bluez`（BT attach 与验收都要它；base 集合不含，desktop 只是被 ubuntu-desktop 顺带拉入） |
| extra_firmware | radxa-firmware 仓拉 AP6256 brcmfmac 三件套 + BT patchram 到 `/lib/firmware/brcm/` |
| bootloader | default 使用平台/SoC 默认；AMP products 追加 `CONFIG_AMP=y` / `CONFIG_ROCKCHIP_AMP=y` |

## AP6256 WiFi/BT

WiFi 走 **mainline brcmfmac**（不是 Rockchip OOT bcmdhd，见下方踩坑）。部署到 `/lib/firmware/brcm/` 的四个文件：

| 文件 | 用途 |
|---|---|
| `brcmfmac43456-sdio.bin` | WiFi 主固件。brcmfmac 对 chip `BCM4345/9` 由 `brcmf_fw_alloc_request()` 拼出该名 |
| `brcmfmac43456-sdio.txt` | NVRAM 校准参数，文件头须为 `#AP6256_NVRAM_*` |
| `brcmfmac43456-sdio.clm_blob` | CLM（Country Locale Matrix），**不可省** |
| `BCM4345C5.hcd` | BT patchram（btbcm） |

配套 kernel 侧两处：

- `kernel.config` 的 `CONFIG_BCMDHD=n`，关掉抢 SDIO 的 OOT 驱动。
- `0001` 改 `rk3566-orangepi-cm4.dtsi` chosen.bootargs：删硬编码 `root=PARTUUID`（避免覆盖 extlinux APPEND，断 normal/recovery 切换）、加 `firmware_class.path=/lib/firmware`。与 tspi-rk3566 0001 同因。

dtsi 的 `wifi_chip_type="ap6256"` 只被 bcmdhd 读取，对 brcmfmac 是惰性属性；SDIO 上电与时钟由 `&sdio` 节点和 `rfkill_rk` 完成，与具体 WiFi 驱动解耦，因此**不需要改 dtsi**。

### 踩坑：两个 WiFi 驱动抢同一块 SDIO 卡

BSP 内核同时编入两个能驱动 BCM43456 的驱动：

- Rockchip OOT `bcmdhd`——`drivers/net/wireless/rockchip_wlan/Kconfig` 中 `menuconfig BCMDHD ... default y`，**不在任何 defconfig 里**，且是 `bool` 型只能内建，所以用户态 `modprobe` blacklist 对它无效，只能在 Kconfig 层关。
- mainline `brcmfmac`——`rockchip_linux_defconfig:668` 的 `=m`，经 SDIO MODALIAS 自动 modprobe。

brcmfmac 先绑定 SDIO func。早期版本只部署了 bcmdhd 命名的固件，brcmfmac 找不到自己要的 `brcmfmac43456-sdio.bin`，于是陷入死循环：

```
brcmfmac: brcmf_fw_alloc_request: using brcm/brcmfmac43456-sdio for chip BCM4345/9
brcmfmac mmc2:0001:1: Direct firmware load for brcm/brcmfmac43456-sdio.bin failed with error -2
brcmfmac: brcmf_sdio_htclk: HT Avail timeout (1000000): clkctl 0x50
mmc2: card 0001 removed
```

周期约 1.4 秒，持续占住 SDIO func，bcmdhd 永远等不到设备（`lsmod` 引用计数恒 0），结果两个驱动都不工作、`ip link` 无 `wlan0`。同款症状见 `armsom-cm5-io`（那块板因 BCM43752 在 mainline 支持不足，选的是相反方向：关 brcmfmac 走 rkwifibt OOT）。

CLM blob 同样是必需项：缺它时固件内置的 Generic.Min CLM 不接受 `set country`，表现为 `country setting failed`、无可用信道、扫不到任何 AP。

### 实机验收

```bash
ip link | grep wlan0                       # 应有 wlan0
dmesg | grep brcmf_c_preinit_dcmds         # 应见 Firmware: BCM4345/9 ... version 7.45.96.61
dmesg | grep -E "error -2|HT Avail"        # 应为空
lsmod | grep bcmdhd                        # 应为空
nmcli dev wifi list                        # 应同时出现 2.4G 与 5G AP
```

`wlan0` 的 MAC 应取自模组 OTP，而非 NVRAM 缺省值 `00:90:4c:c5:12:38`——若等于缺省值说明 NVRAM 未正确生效。

### 蓝牙开机自动 attach

dtsi 只以独立的 `wireless-bluetooth` 平台节点（Rockchip `rfkill_rk`）描述 BT，`uart1` 下**没有** serdev 形态的 `bluetooth` 子节点，所以内核 `hci_uart` 不会自动 attach——即便 `CONFIG_BT_HCIUART_SERDEV=y` / `CONFIG_SERIAL_DEV_BUS=y` 都已启用。`bluetooth.service`(bluetoothd) 只管理已存在的 hci 设备，不做 attach。板级因此自备两个 overlay 文件：

| 文件 | 作用 |
|---|---|
| `etc/systemd/system/bluetooth-orangepi-cm4.service` | `Type=simple` 跑 `btattach -B /dev/ttyS1 -P bcm` |
| `etc/systemd/system/multi-user.target.wants/…`（符号链接） | 等价于 `systemctl enable`——overlay 经 `cp -a` 应用会保留符号链接，这是 overlay 层唯一的 enable 手段 |
| `usr/lib/flange/bt-unblock.sh` | `ExecStartPre` 调用，解除 rfkill 软阻断 |

**两个坑**：

1. **必须 `Type=simple`，不能 `oneshot`**。`btattach` 不 daemonize，attach 后持续持有 line discipline，进程一退出 `hci0` 就消失。用 `Type=oneshot` 会卡在 activating 直到 `TimeoutStartSec` 超时被 kill，连带把 `hci0` 带走。（`khadas-vim3l` 的同类 unit 用的正是 oneshot，且其 overlay 缺 `wants` 符号链接，从未被 enable。）
2. **`rfkill unblock bluetooth` 对 `rfkill_rk` 无效**。该驱动没把 `set_block` 的结果回写到 `soft` 属性，命令返回成功但 `soft` 仍是 1；只能直接写 `/sys/class/rfkill/<n>/soft`。而且 `systemd-rfkill` 会把 blocked 状态持久化到 `/var/lib/systemd/rfkill/platform-wireless-bluetooth:bluetooth` 并每次开机恢复。索引不能写死——`hci0` 就位后自己也会注册成一个 rfkill 节点，索引会右移。

`btattach` 与 `hciconfig` 都来自 `bluez`，而 rootfs `base` 包集合不含它，故板级 `rootfs.packages` 显式声明，让 `default` / `amp` product 也拿得到。

**验收**：

```bash
ls /sys/class/bluetooth/                        # 应有 hci0
systemctl is-active bluetooth-orangepi-cm4      # active
hciconfig -a                                    # hci0 UP RUNNING，errors:0
dmesg | grep BCM4345C5                          # 应见 'brcm/BCM4345C5.hcd' Patch 与 BT 5.2
bluetoothctl scan le                            # 应能收到广播事件
```

BD Address 应与 WiFi MAC 连号（实测 BT `C0:F5:35:41:28:97` / WiFi `…:96`），说明取自模组 OTP。

BT 应用层栈（配对策略、音频 profile）不预装，由产品方自取。

**更干净但未采用的路线**：给 `uart1` 加 `compatible = "brcm,bcm4345c5"` 的 `bluetooth` 子节点走 serdev，由内核自动 attach，可省掉 `bluez` 与常驻进程。没做是因为 BSP 的 `wireless-bluetooth` 节点持有 `BT,reset_gpio=79`，serdev 子节点要用同一个 GPIO 作 `shutdown-gpios`，冲突需先禁用前者，且该 BSP 上 serdev 路径无先例、需实机反复试。

## NPU

`rk356x.dtsi` 默认禁用 `rknpu` / `rknpu_mmu`，但 Orange Pi CM4 dtsi 又改成 `okay`。实机日志显示 `rknpu_mmu` probe 拉起 NPU power domain 后，PMU 等不到 `npu` ack，会触发 BSP `panic_on_set_idle`。`0003` 把两处状态改回 `disabled`，优先保证默认镜像可启动。

## AMP

`orangepi-cm4-amp-debug` / `orangepi-cm4-amp-release` 使用 HAL AMP demo；
`orangepi-cm4-amp-rtt-debug` / `orangepi-cm4-amp-rtt-release` 使用 RT-Thread demo。
两个 AMP product 都把 cpu3 交给从核固件，Linux 跑 cpu0/1/2，并在分区表里追加非 raw 的
`amp` ext4 分区。

Orange Pi CM4 40pin 未引出 `tspi-rk3566` 默认使用的 UART4_M1，因此本板 AMP 从核 console 固定用
UART7_M2：

| 40pin | SoC GPIO | 功能 |
|---|---|---|
| 15 | GPIO4_A2 | UART7_TX_M2 |
| 16 | GPIO4_A3 | UART7_RX_M2 |

实现位置：

- `0004-add-orangepi-cm4-amp-dts.patch` 新增 `rk3566-orangepi-cm4-amp.dts`，把 `rockchip-amp` 的
  clock / pinctrl / console IRQ 切到 `SCLK_UART7`、`PCLK_UART7`、`uart7m2_xfer`、`UART7_IRQn`。
- `components/app/rk3568_amp_uart7_demo` 初始化 UART7_M2，HAL console baud rate 为 1500000。
- `components/app/rk3568_amp_uart7_rtt_demo/.config` 选择
  `CONFIG_RT_CONSOLE_DEVICE_NAME="uart7"`，关闭 `RT_USING_UART4`，启用 `RT_USING_UART7`，
  RT-Thread console baud rate 为 115200。

## DSI 屏适配（未交付，单独立项）

实机底板是 Waveshare CM4-DISP-BASE-5A（5" DSI 屏），桥芯片 Chipone ICN6211 在 i2c1@0x2c，EN 板上拉死高无独立 reset GPIO。本轮 change（`orangepi-cm4-bringup-wifi-and-npu-fix`）尝试一次性带屏适配但实机不能正常启动，已撤回。详细踩坑见 `wiki/log.md` 2026-05-17 条目：

- dtsi 错抄的 RPi 7" panel 模板（`raspits_panel@45` / `raspits_touch_ft5426@38`）与实际 ICN6211 链路不匹配
- BSP `drm_mipi_dsi.c::mipi_dsi_remove_device_fn` 缺 `bus_type` 校验，DSI defer cleanup NULL deref（上游 commit `7977c539e9b1` 等价 fix 未合）
- `CONFIG_DRM_CHIPONE_ICN6211` 未启用，driver 编不进
- mainline ICN6211 driver 强制要求 `enable-gpios`，与本板硬件不符
- dtso 根级新增节点必须 `&{/} {}` 显式包成 fragment，否则 u-boot `FDT_ERR_BADOVERLAY`

未来开屏适配 change 时直接复用上述路标。

## overlay

`overlay/etc/hostname` + `overlay/etc/usbdevice.conf`，无额外定制内容。
