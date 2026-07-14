# rockchip-atk-rk3506b-wifibt Specification

## Purpose

定义 ATK-RK3506B 板载 RTL8733BUUA 的 USB 硬件拓扑、固定版本 OOT driver、
最小 firmware/rootfs 集成与实机验收契约，避免误用 AP6256 的 SDIO/UART 配置。

## Requirements
### Requirement: RTL8733BUUA USB 硬件拓扑

系统 MUST 把 ATK-RK3506B 板载 RTL8733BUUA 作为 USB2 OTG1 下 CH334R Hub 的
USB composite device 使用，并 MUST NOT 为其启用 SDIO、MMC pwrseq、UART5 serdev
或 WiFi/BT 专用 GPIO node。系统 MUST 保持 USB gadget OTG0 与 UART4 AMP 路由不变。

#### Scenario: 实机 USB 枚举与 interface 匹配

- **WHEN** 设备启动并枚举 USB2 OTG1
- **THEN** CH334R Hub 以 `1a86:8091` 出现，RTL8733BUUA 以 `0bda:b733` 出现
- **THEN** Bluetooth interfaces 为 `e0/01/01`，WiFi interface 为 `ff/ff/ff`

#### Scenario: 不破坏既有板级路由

- **WHEN** 应用 ATK-RK3506B WiFi/BT 适配
- **THEN** 不新增 board kernel DTS patch
- **THEN** MMC、UART5、GMAC1、UART4 AMP 与 USB gadget DT 配置保持原样

### Requirement: RTL8733BU WiFi driver

系统 MUST 从固定 git commit 构建 RTL8733BU USB OOT driver，并通过 module alias
自动绑定 `0bda:b733` 的 `ff/ff/ff` interface。系统 MUST NOT 启用 BCMDHD、AP6XXX
或其它 SDIO WiFi driver 作为该模组的实现。

#### Scenario: 构建并安装 WiFi module

- **WHEN** 构建 ATK-RK3506B kernel 与 modules staging
- **THEN** 生成并安装 `updates/8733bu.ko`
- **THEN** `modules.alias` 包含 `0BDA/B733` USB interface 到 `8733bu` 的映射

#### Scenario: 自动创建 WLAN interface

- **WHEN** RTL8733BUUA 枚举且 udev 处理 USB modalias
- **THEN** `8733bu` 自动加载并创建可由 NetworkManager 管理的 WLAN interface

### Requirement: RTL8733BU Bluetooth driver

系统 MUST 使用固定 git commit 的 Realtek USB HCI OOT driver 初始化 Bluetooth，
并 MUST 使用同源的 `rtl8733bu_fw` 与 `rtl8733bu_config`。系统 MUST NOT 使用
BCM HCI UART、serdev、Broadcom HCD 或 UART attach service。

#### Scenario: Bluetooth module 与 firmware 精确安装

- **WHEN** 构建 kernel 与 rootfs
- **THEN** 安装 `updates/rtk_btusb.ko`
- **THEN** `/lib/firmware/rtl8733bu_fw` 与 `/lib/firmware/rtl8733bu_config` 存在
- **THEN** 不安装 AP6256/Broadcom firmware 三件套

#### Scenario: 自动注册 HCI controller

- **WHEN** `0bda:b733` Bluetooth interfaces 枚举
- **THEN** `rtk_btusb` 自动绑定、下载 firmware 并注册 HCI controller
- **THEN** BlueZ 能列出 controller 并执行 discovery

### Requirement: 最小且可复现的用户空间

系统 MUST 固定 WiFi 与 Bluetooth source commit，仅额外安装 BlueZ 与两份
RTL8733BU Bluetooth firmware，并复用 base rootfs 的 NetworkManager 与
wpa_supplicant。

#### Scenario: source 与 rootfs 依赖受控

- **WHEN** 解析 ATK-RK3506B 最终配置
- **THEN** 两份 OOT source 均声明完整 commit hash
- **THEN** package list 包含 BlueZ、NetworkManager 与 wpa_supplicant
- **THEN** 不包含完整 linux-firmware、AP6256 package 或 UART patchram App

### Requirement: 实机功能验收

系统 MUST 在刷写后验证 RTL8733BUUA 的自动枚举、WiFi 与 Bluetooth 基本通信，
并回归既有网络、AMP 与调试链路。

#### Scenario: WiFi 基本通信

- **WHEN** 设备冷启动并连接测试 AP
- **THEN** 能扫描 2.4 GHz 与 5 GHz network、完成 association 并通过 IP connectivity test

#### Scenario: Bluetooth 基本通信

- **WHEN** BlueZ ready
- **THEN** HCI controller 为 UP 状态且能扫描附近 discoverable Bluetooth device

#### Scenario: reboot 与 regression

- **WHEN** 设备完成正常 reboot
- **THEN** WLAN 与 HCI controller 无需人工 modprobe 即可恢复
- **THEN** GMAC0/GMAC1、UART4 MSH、RPMsg 与 ADB 继续工作
