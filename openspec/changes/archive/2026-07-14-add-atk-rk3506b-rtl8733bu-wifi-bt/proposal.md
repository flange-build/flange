## Why

ATK-RK3506B 实机安装的是 RTL8733BUUA WiFi/蓝牙二合一模组，而不是 AP6256。
原理图显示模组的 `USB_DP/USB_DM` 接 CH334R USB Hub 第 3 路，Hub 上行连接
RK3506B 的 USB2 OTG1；实机也枚举为 `0bda:b733` USB composite device。
当前内核没有匹配该设备的 WiFi module，Bluetooth USB interface 也未绑定驱动，
因此系统没有 WLAN 或 HCI controller。

先前按 AP6256 假设增加的 SDIO、UART5 与 Broadcom firmware 配置不符合硬件，
还会让 UART5 抢占 GMAC1 pinmux。需要删除这条错误链路，改为最小、可复现的
RTL8733BU USB 驱动与固件集成。

## What Changes

- 删除 AP6256 专用 DTS patch，不修改 MMC、UART5、GMAC1 或现有 USB host 路由。
- 通过现有 OOT module 机制构建固定 commit 的 RTL8733BU USB WiFi driver，
  生成 `8733bu.ko` 并用 USB modalias 自动加载。
- 构建固定 commit 的 Realtek USB Bluetooth HCI driver，生成 `rtk_btusb.ko`，
  同时只部署配套的 `rtl8733bu_fw` 与 `rtl8733bu_config`。
- 移除 BCMDHD/AP6XXX、BCM HCI UART 与 AP6256 三件套固件，仅保留 BlueZ 作为
  Bluetooth 用户态管理工具。
- 更新板级测试、Wiki 和验收证据，明确 USB topology、VID:PID、driver 来源与
  实机验证方法。

## Capabilities

### New Capabilities

- `rockchip-atk-rk3506b-wifibt`: ATK-RK3506B 上 RTL8733BUUA 的 USB WiFi、
  USB Bluetooth、firmware 安装、自动加载与实机验收能力。

### Modified Capabilities

无。

## Impact

- 板级配置：`components/board/atk-rk3506b/config.py`
- 删除错误补丁：`components/board/atk-rk3506b/patches/kernel/0002-enable-ap6256-wifi-bluetooth.patch`
- OOT 兼容补丁：`components/board/atk-rk3506b/patches/rtl8733bu/0001-disable-removed-regulatory-flag.patch`
- rootfs：BlueZ 与两份 RTL8733BU Bluetooth firmware
- 测试：`tests/config/test_atk_rk3506b.py`
- 文档：`wiki/boards/atk-rk3506b.md`
- 外部依赖：两份固定 git commit 的 GPL vendor driver，其中 Bluetooth source
  同时提供配套 firmware

## 非目标

- 不改变 USB gadget 使用的 OTG0、UART4 + RPMsg AMP、SPI NAND、FIT boot、
  分区表或 UBI/UBIFS 布局。
- 不改造 Device Tree（设备树）中的 SDIO、UART5 或 WiFi platform node。
- 不提供 WiFi 热点、配网 UI、Bluetooth audio policy 或产品业务协议。
