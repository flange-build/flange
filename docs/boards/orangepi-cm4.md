# orangepi-cm4

> 阅读前提：先完成[初学指南](../first-steps.md)的环境准备，运行
> `flange target list orangepi-cm4` 确认当前目标，再按该型号硬件说明匹配介质、接口与下载模式。
> 本页是配置摘要与硬件记录；下文验收只覆盖记录的版本、产品和测试项，不代表当前全部组合已实测。
> [返回板卡索引](README.md) · [构建与刷写流程](../development-guide.md)

## 概述

Orange Pi CM4，RK3566 计算模块。当前交付范围：**无屏可启动 + AP6256 WiFi/BT 即插即用**，NPU 可用（实板验证），并提供可选 `amp` / `amp-rtt` product。`waveshare-display-5a` product 适配 Waveshare CM4-DISP-BASE-5A VER2 底板（5" DSI 触摸屏、RTC、风扇、USB hub），**实板验收通过**（含 HDMI 与屏同时输出）。

## product / variant

板级声明：`products: [default, desktop, amp, amp-rtt, waveshare-display-5a]`，`variants: [debug, release]`。

```
lunch orangepi-cm4-default-debug
lunch orangepi-cm4-default-release
lunch orangepi-cm4-amp-debug
lunch orangepi-cm4-amp-release
lunch orangepi-cm4-amp-rtt-debug
lunch orangepi-cm4-amp-rtt-release
lunch orangepi-cm4-waveshare-display-5a-debug
lunch orangepi-cm4-waveshare-display-5a-release
```

## 关键差异点

| 项 | 值 |
|---|---|
| DTB | default 用 `rk3566-orangepi-cm4-base`（保持空壳）；AMP products 用 `rk3566-orangepi-cm4-amp` |
| board overlay | 无（dsi1 维持 dtsi 默认 disabled） |
| kernel patches | `0001` bootargs、`0004` AMP dts、`0005` DSI 对 I2C 面板改在 host attach 时 component_add、`0006` 面板像素时钟与 DSI lane 速率对齐 |
| board dtso | `waveshare-display-5a` product 专用：底板外设 `rk3566-orangepi-cm4-waveshare-display-5a.dtbo` 与屏 `…-5a-panel.dtbo`，均编译并默认加载 |
| bootloader patches | `0001` U-Boot 阶段打开 vdd_npu（RK809 DCDC4） |
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

Orange Pi CM4 dtsi 把 `rknpu` / `rknpu_mmu` 设为 `okay`，NPU 供电是 RK809 DCDC4（`vdd_npu`）。早期因 `rknpu_mmu` probe 拉起 NPU power domain 时 PMU 等不到 `npu` ack（`panic_on_set_idle`）而禁用过 NPU，当时误判为硬件不可用；根因其实是 vdd_npu 在内核开电源域时尚未上电，见 [rockchip 平台](../platforms/rockchip.md)「RK356x NPU 供电」。现由 bootloader `0001` 在 U-Boot 阶段打开 vdd_npu（0.9V），实板验证：`vdd_npu ... 900 mV, enabled`、`rknpu 0.9.8` 加载、debugfs `power on` 后 NPU PD `on` / IOMMU `active`。尚未跑 RKNN 推理。

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

## Waveshare CM4-DISP-BASE-5A 底板（waveshare-display-5a）

`lunch orangepi-cm4-waveshare-display-5a-<variant>`。底板差异分两个板私有 overlay，均默认加载：外设（RTC / 风扇 / USB host）`rk3566-orangepi-cm4-waveshare-display-5a.dtso`，5" DSI 屏 `…-5a-panel.dtso`。面板 / 触摸驱动沿用 defconfig 的内建。另有风扇温控服务，追加 `i2c-tools` 便于排查。**状态：屏（画面对正）、触摸、RTC、风扇、USB hub、HDMI 与屏同时输出均实机通过。** 下表“依据”列说明每项结论来自哪里。

DSI 屏的两个关键结论：

- **DSI 与 I2C 面板的 probe 顺序（`0005`）**：Rockchip BSP 的 DSI 在 probe 时就 `component_add`，bind 要求面板已 `drm_panel_add`，否则 probe 失败并注销 DSI host；`panel-raspberrypi-touchscreen` 挂在 I2C 上，要先查到已注册的 DSI host 才能注册 DSI 设备并 `drm_panel_add`。两边互等，HDMI 子设备（`dw-hdmi-cec` 等）的 probe 又不断触发 deferred 重试，内核空转在 deferred probe 里挂不上 rootfs（串口上 `failed to find panel or bridge: -517` 循环），面板驱动编成模块也一样。`0005` 对“外设不是 DSI 子节点”的情况改用 mainline 做法：probe 只注册 host，外设 `mipi_dsi_attach()` 时经 `host_ops->attach` 再 `component_add`；外设是 DSI 子节点的 BSP 原有流程不变。Synopsys 核心的 `host_attach` 同时补上平台回调失败时的回滚，避免外设 deferred 重试时 `drm_bridge_add()` 重复入链。代价：启用屏后 Rockchip DRM 要等面板 attach 才 bind，屏没接或面板 probe 失败时 HDMI 也不出图。
- **像素时钟必须等于 lane 速率 / 24（`0006` + `rockchip,lane-rate`）**：面板走非 burst 同步脉冲模式、1-lane RGB888。BSP 默认按像素时钟向上取整到 MHz 后 ×24/0.9 推算 lane 速率（25.979 MHz → 696 Mbps），链路比像素流快约 11.6%，DSI 发完一行时 VOP 还没送完，差额在 DW DSI 像素 FIFO 里形成固定积压，画面右移 800 × (1 − 像素速率 / 链路速率) ≈ 80 px 并卷绕上一行末尾。特征是 DSI 自带 pattern generator（debugfs `fe070000.dsi/vpg`）出图是正的，改 porch / 像素时钟、切 burst 模式都不改变偏移。RPi 的 vc4 会把像素时钟抬到与链路匹配，原 modeline 在 RPi 上没有这个问题。修法：panel dtso 用 `rockchip,lane-rate = <696>` 固定链路，`0006` 把面板 mode 改为 29 MHz（= 696 / 24）、HFP 1 → 100（59.98 Hz）。**两处必须成对修改**。

| 底板功能 | 适配方式 | 依据 |
|---|---|---|
| 5" DSI 屏 | `&dsi1`（`rockchip,lane-rate = <696>`）+ `&dsi1_in_vp1` + `&video_phy1` + vendor dtsi 现成的 `raspits_panel@45`（i2c1，BSP `panel-raspberrypi-touchscreen`，800×480、1-lane，mode 经 `0006` 改为 29 MHz / HFP 100） | Waveshare 对 VER2 的官方用法为 RPi `dtoverlay=vc4-kms-dsi-7inch`（DSI1 + I2C-10），即板上 MCU 仿真 RPi 7" 屏的 ATTiny 协议 |
| 电容触摸 | vendor dtsi 的 `raspits_touch_ft5426@38`（BSP 轮询驱动，800×480） | 同上 |
| RTC PCF85063A @0x51 | i2c1 新增节点；`/aliases` 把它定为 `rtc0`、RK809 RTC 让到 `rtc1` | Waveshare wiki + 原理图；hctosys 与 `/dev/rtc` 默认用 rtc0 |
| 风扇 EMC2301 @0x2f | i2c1 新增节点（`emc2305` 驱动，=m 自动加载）+ `waveshare-fan.service` 按 soc-thermal 分档写 `pwm1`（45/55/65°C → 40%/70%/100%，降档回差 5°C） | 原理图 |
| 4 口 USB2 hub | `&usbdrd_dwc3 { dr_mode = "host"; }` | 原理图：FSUSB42 在 BOOT 拨码 OFF 时把 CM4 USB0 接到 FE1.1s hub，ID 脚悬空 |
| 千兆网口 / HDMI0 / M.2(PCIe) / TF 卡 / 40PIN | 基础 dts 已启用，无改动 | vendor dtsi |

CM4 引脚到 RK3566 控制器的映射（SCL0/SDA0 → `i2c1`、DSI1 → `dsi1`、ID_SD/ID_SC → `i2c3`、40PIN GPIO2/3 → `i2c2` m1）取自 vendor dtsi 的节点配对与 40pin 复用表，没有 Orange Pi CM4 原理图佐证。

### 已知限制与取舍

- **没有 USB adb / gadget**：OTG 口固定为 host，正常运行时调试走千兆网口 ssh。BOOT 拨码 ON 时 USB0 切到 Type-C 烧录口（同时拉低 nRPIBOOT，它在 Orange Pi CM4 上的作用未验证）。
- **风扇温控在用户态**：RK3566 只有两路 tsadc，已被 soc-thermal / gpu-thermal 各占一路（`thermal_of` 一路传感器只能挂一个热区），而两个热区都跑 `power_allocator`，它不会驱动非功率型 cooling device。服务由 udev 在 `emc2305` hwmon 出现时经 `SYSTEMD_WANTS` 拉起，其它 product 上不会启动。
- **RTC 中断**：底板默认把 RTC INT 接到 PI_RUN（闹钟触发复位），不接 SoC GPIO，dtso 不声明中断。
- **RTC/FAN I2C 跳线**：按默认（SDA0/SCL0）适配。跳到 GPIO2/3 时两颗芯片会挂到 i2c2，需要改 dtso。
- **摄像头**：CSI 接口取决于所接模组（ov5647 / imx219 等），需 ISP IQ 文件等配套，未纳入本 product。
- 仅适用 VER2。Waveshare 公开的（部分）原理图是 ICN6211 直连 CM4 DSI0，与 VER2 官方用法不一致。

### 实机验收

```bash
i2cdetect -y 1                    # 应见 0x2f(风扇) 0x38(触摸) 0x45(屏控 MCU) 0x51(RTC，驱动占用显示 UU)
dmesg | grep -iE "rpi_touchscreen|raspits|dsi"   # 不应有 "Atmel I2C read failed" / "Unknown Atmel firmware revision"
cat /sys/class/drm/card*-DSI-1/status            # connected
grep dclk_vop1 /sys/kernel/debug/clk/clk_summary  # 29000000（0006 生效）；画面左右边缘对齐、无卷绕
evtest                            # 触摸四角坐标约 (0,0)/(800,0)/(0,480)/(800,480)
cat /sys/class/rtc/rtc0/name      # 应为 rtc-pcf85063
hwclock -w && hwclock -r          # 写读 RTC；断电（装 CR1220）后重启时间应保留
systemctl status waveshare-fan    # active；温度升降时日志打印档位变化
lsusb -t                          # 应见 FE1.1s hub 及其下游设备
```

实测（2026-11-08，debug 镜像）：`i2cdetect -y 1` 见 0x2f / 0x38 / 0x45 / 0x51，0x45 的 REG_ID 为 0xc3（RPi 7" ATTiny v2 固件），0x38 为 FT5426；`rtc0 = rtc-pcf85063`，`emc2305` hwmon 与 `waveshare-fan` 服务正常，FE1.1s 4 口 hub 枚举；开机 11.7 s（内核 2.9 s + 用户态 8.9 s），无失败单元；DSI 首次 attach 报一次 `-517` 后 bind 成功，`card0-DSI-1` connected / 800x480，mode 为 29 MHz / HFP 100，`dclk_vop1` 29.000 MHz，`VID_HLINE_TIME` 2844（即 lane 696 Mbps）；屏上刻度尺左右对正、无卷绕（用户目视）；`fts_ts` 四角坐标约 (31,24) / (788,41) / (14,441) / (770,434)，原点在左上、X 向右、Y 向下，与显示同向，`XY_REVERSE` 无需调整。屏点亮时热插 HDMI，vp0 输出 720x480p60（dclk 27.027 MHz），vp1 上的 DSI 不受影响，两路同时出图（用户目视）。

屏默认启用。只想回退屏时，从 `/boot/extlinux/extlinux.conf` 的 `fdtoverlays` 删掉 `-panel.dtbo` 并重启。

屏不亮时的判断顺序（串口 1500000 波特率）：`dmesg | grep -iE "dsi|rpi_touchscreen|vop|flip_done"` 看面板注册、bind 与 modeset，开机阶段 DSI 设备首次 attach 报一次 `-517` 属预期，反复出现说明 `0005` 没生效；`ls /sys/class/drm` 应有 `card*-DSI-1`。若 connector 存在、modeset 无报错但无画面，先查排线与底板供电。画面横向错位并卷绕时，核对 `/proc/device-tree/dsi@fe070000/rockchip,lane-rate`（应为 696）与 `dclk_vop1`（应为 29 MHz）；DSI 寄存器 `0xfe070050`（`VID_HLINE_TIME`）= htotal × lane Mbps / 8 / 像素 MHz，可反推实际 lane 速率。

### DSI 卸载与 overlay 限制

BSP 的 `mipi_dsi_remove_device_fn` 缺少 bus 过滤，手动 unbind DSI 驱动可能把非 DSI 子设备按 DSI 类型解引用而崩溃；当前面板补丁避开正常 probe 失败时的注销路径，但未修复所有手动卸载场景。DT overlay 根级新增节点仍须使用 fragment，否则 U-Boot 会报 `FDT_ERR_BADOVERLAY`。

## overlay

`overlay/etc/hostname`、`overlay/etc/usbmode/gadget.d/20-orangepi-cm4.yaml`、蓝牙 attach 服务（见上文），以及 `waveshare-display-5a` 用的风扇温控三件套（`waveshare-fan.service` + `90-waveshare-fan.rules` + `usr/lib/flange/waveshare-fan.sh`）。rootfs overlay 不区分 product，风扇服务靠 udev 匹配 `emc2305` hwmon 才启动，其它 product 上是惰性文件。
