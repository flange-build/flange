## Context

原理图与实机共同确认如下连接：

```text
RK3506B USB2 OTG1 (host)
  -> CH334R USB Hub (1a86:8091)
     -> port 3 RTL8733BUUA (0bda:b733)
        -> interface 1.0/1.1: Bluetooth e0/01/01
        -> interface 1.2: WiFi ff/ff/ff
```

模组 `CHIP_EN` 由 3.3 V 上拉，原理图中的 SDIO、UART、wake GPIO 均不存在。
当前 DTB 已让 `ff780000.usb` 以 host mode 工作，并能枚举 Hub 与 RTL8733BUUA，
所以板级路由无需修改。此前 AP6256 patch 启用 UART5 后与 GMAC1 GPIO3 pinmux
冲突，是完全错误的硬件建模。

原厂 SDK `atk_dlrk3506_linux6.1_release_v1.3.1_20260326` 使用
`CONFIG_RTL8733BU=m` 与 `CONFIG_BT_RTK_HCIBTUSB=m`，Bluetooth firmware 为
`/lib/firmware/rtl8733bu_fw`、`rtl8733bu_config`。flange 指定的
`linux-6.1-stan-rkr5.1` commit `847bc9cd7ecd` 不包含 RTL8733BU WiFi source，
其旧 `rtk_btusb` 也没有 `0bda:b733` entry，因此不能仅追加 Kconfig symbol。

系统只有 512 MiB DDR 与 512 MiB SPI NAND，rootfs 为 414 MiB UBI，driver 与
firmware 必须按芯片最小集合安装。

## Goals / Non-Goals

**Goals:**

- 让 `0bda:b733` WiFi interface 自动绑定 `8733bu.ko` 并创建 WLAN interface。
- 让同一 composite device 的 Bluetooth interfaces 自动绑定 `rtk_btusb.ko`，
  加载配套 firmware 并注册 HCI controller。
- driver 与 firmware source 固定 commit，构建可复现且不依赖开发机 Downloads。
- 删除所有 AP6256、SDIO、UART5 与 Broadcom firmware 遗留，恢复 GMAC1 pinmux。

**Non-Goals:**

- 不改变已经能工作的 USB2 OTG1 host、CH334R Hub 或 USB gadget OTG0 配置。
- 不把 20 MiB 以上 vendor source vendoring 到 flange repository。
- 不提供热点、Bluetooth audio、低功耗 wakeup 或长期吞吐测试。

## Decisions

### 1. Device Tree 不做 WiFi/BT 专用修改

RTL8733BUUA 是标准 USB composite device，现有 DTB 已完成 host controller、PHY
与 Hub 枚举。USB device driver 通过 VID:PID 与 interface class 匹配，不需要
`wireless-wlan`、MMC pwrseq、UART serdev 或 wake GPIO node。删除 AP6256 patch
后，MMC 与 UART5 回到原始配置，GMAC1 不再被 UART5 抢 pin。内核只保留
通用 cfg80211、Bluetooth、rfkill 与 crypto core，并关闭 `WL_ROCKCHIP`、
`RFKILL_RK`，避免为纯 USB 模组引入 SDIO/GPIO platform glue。

### 2. WiFi 使用固定版本的 OOT RTL8733BU driver

使用 `wirenboard/rtl8733bu` branch `v5.13.0.1-112`、commit
`2d9048be60759206b8db5e2370420333ef0b8478`。该 driver 与官方 BSP 使用相同的
`v5.13.0.1-112-g10248f4f3.20230626` 基线，并明确匹配
`USB_DEVICE_AND_INTERFACE_INFO(0x0bda, 0xb733, 0xff, 0xff, 0xff)`，可按标准
Kbuild OOT 方式针对当前 ARM32 kernel 生成 `8733bu.ko`。WiFi firmware 已编入
module，不额外占用 rootfs firmware collection。构建关闭 `CONFIG_RTW_DEBUG` 与
`CONFIG_PROC_DEBUG`，并复用官方 BSP Makefile 中的 `-Wno-unused-function`、
`-Wno-discarded-qualifiers`；这是对 vendor code 在 `CONFIG_WERROR=y` 下的定向
warning suppression。公开基线还引用了当前 gitlab-r Linux 6.1 已移除的
`REGULATORY_IGNORE_STALE_KICKOFF`；使用一个只注释该赋值的 OOT source patch，
与 ATK 官方 SDK 同版 driver 的处理完全一致。该 patch 不触碰 Device Tree、USB
路由或驱动功能代码，并在构建前先还原固定 commit 后幂等应用。

直接导入原厂 681 个 source file 会给 flange 增加约 20 MiB vendor code，且以后
同步困难；固定外部 commit 能复用现有 `oot_sources/oot_modules` cache 与 `depmod`
机制，source HEAD 也进入 kernel content hash。

### 3. Bluetooth 使用 Realtek USB HCI OOT driver 与同源 firmware

使用 `fengyuzhong/rtl8733bu-bt` branch `master`、commit
`dc7b30b4b9d2c5437a80bfaff6c8a77c97642778`。它的 USB driver 对
`0x0bda:0xb733` 使用 `rtl8733bu_fw` 与 `rtl8733bu_config`，与原厂 SDK 的
driver/firmware contract 一致。构建 `rtk_btusb.ko` 时关闭 in-tree `btusb`，
避免两个 HCI driver 竞争同一 interface。

firmware 从同一固定 source 的 `rtkbt-firmware/lib/firmware/` 复制到
`/lib/firmware/`。只安装 56,676-byte firmware 与 14-byte config，不引入完整
rkwifibt 或 linux-firmware。

### 4. 用户态只增加 BlueZ

NetworkManager 与 wpa_supplicant 已在 base package set 中，WiFi 无需板级 service。
Bluetooth controller 由 kernel module 初始化，BlueZ 提供 daemon 与 CLI；不运行
UART attach、patchram 或 GPIO 脚本。

## Risks / Trade-offs

- [OOT vendor driver 与 kernel API 的兼容性] → 在 Docker 中用项目固定 GCC 10.3
  针对最终 kernel tree 构建；公开 WiFi 基线与官方 SDK 的一行 regulatory 差异
  以独立最小 patch 固化，并把 module alias 与实机 probe 纳入验收。
- [公开 Bluetooth firmware 比原厂 SDK 版本更新] → driver 与 firmware 使用同一
  source commit；实机验证 firmware download、HCI scan 与 reboot 恢复。
- [USB Hub 上还有外接 USB-A 设备] → driver 只按 `0bda:b733`/interface class 绑定，
  不改变 Hub 与其它 port，验收中回归 USB gadget、Ethernet 与 ADB。
- [vendor WiFi module 体积较大] → 关闭 driver debug，strip debug symbols，并核对
  rootfs.ubi 仍满足 414 MiB partition gate。

## Migration Plan

1. 删除 AP6256 DTS patch、Kconfig 与 firmware，增加两份固定 OOT source/module。
2. 更新测试、Wiki、OpenSpec，并运行 config/OpenSpec validation。
3. 增量构建 kernel/rootfs/boot/image，核对 `8733bu.ko`、`rtk_btusb.ko`、modalias
   与两份 firmware。
4. 刷写后验证 WLAN、HCI、reboot，以及 GMAC1/UART4/RPMsg/ADB regression。

## Open Questions

无。Bluetooth low-power wakeup 不在本次范围，后续有需求时单独立项。
