# RTL8733BUUA 适配验收证据

## 基线与硬件事实

- 原厂 SDK：`atk_dlrk3506_linux6.1_release_v1.3.1_20260326`。
- 原理图：RTL8733BUUA `USB_DP/USB_DM` 接 CH334R port 3，Hub 上行接 RK3506B USB2 OTG1；
  `CHIP_EN` 由 3.3 V 上拉，不存在 SDIO、UART 或 wake GPIO 连接。
- 实机 USB：CH334R=`1a86:8091`，RTL8733BUUA=`0bda:b733`。
- RTL8733BUUA interface：`1.0/1.1=e0/01/01`（Bluetooth），`1.2=ff/ff/ff`（WiFi）。
- 当前 DTB 已通过 `dwc2 ff780000.usb` 枚举上述设备，证明 USB host/PHY 路由可用。
- 适配前没有 driver binding、WLAN interface 或 HCI controller；UART4/RPMsg/ADB 正常。

## 原厂 BSP 对照

- `rk3506-alientek.config`：`CONFIG_RTL8733BU=m`、`CONFIG_BT_RTK_HCIBTUSB=m`。
- WiFi driver 的 USB table 明确匹配 `0x0bda:0xb733` 的 `ff/ff/ff` interface。
- Bluetooth driver 的 device table 明确把 `0xb733` 映射到 `rtl8733bu_fw` 与
  `rtl8733bu_config`。
- BSP rootfs overlay 只安装这两份 Bluetooth firmware。

## 固定来源

| 内容 | 来源 commit |
|---|---|
| RTL8733BU WiFi driver | `wirenboard/rtl8733bu@2d9048be60759206b8db5e2370420333ef0b8478` |
| Realtek USB Bluetooth driver/firmware | `fengyuzhong/rtl8733bu-bt@dc7b30b4b9d2c5437a80bfaff6c8a77c97642778` |

公开 WiFi 基线相对 ATK 官方 SDK 只有一项影响 Linux 6.1 构建的 source 差异：
官方已注释 `REGULATORY_IGNORE_STALE_KICKOFF` 赋值。flange 使用独立的一行 OOT
兼容补丁复现该处理；构建前先 `git checkout -- .`，再应用补丁，重复构建幂等。

## 静态与构建验收

- ATK-RK3506B 配置测试：23 项通过。
- 相关 source/package/board builder regression：55 项通过。
- `openspec validate add-atk-rk3506b-rtl8733bu-wifi-bt --strict`：通过。
- `flange build kernel -f`：通过；kernel release 为 `6.1.115+`，两个 module 均为
  ARMv7 32-bit，vermagic 为 `6.1.115+ SMP preempt mod_unload ARMv7 thumb2 p2v8`。
- 最终 `.config`：`CONFIG_CFG80211=y`、`CONFIG_MAC80211=y`、`CONFIG_BT=y`、
  `CONFIG_RFKILL=y`；`CONFIG_BCMDHD`、`CONFIG_BT_HCIBTUSB`、
  `CONFIG_BT_HCIUART`、`CONFIG_WL_ROCKCHIP`、`CONFIG_RFKILL_RK` 均关闭。
- `8733bu.ko` version：
  `v5.13.0.1-112-g10248f4f3.20230626_COEX20230616-330e`；`modules.alias`
  包含 `usb:v0BDApB733...icFFiscFFipFF... 8733bu`。
- `rtk_btusb.ko` version：`3.1.65ab490.20240531-141726`；`modules.alias`
  包含 `e0/01/01` Bluetooth interface class 到 `rtk_btusb` 的映射。
- modules staging 与 `modules.dep` 已包含 `updates/8733bu.ko` 和
  `updates/rtk_btusb.ko`，`depmod` 索引刷新成功。

| 最终内容 | 大小 | SHA-256 |
|---|---:|---|
| `updates/8733bu.ko` | 1,772,132 B | `555bdc3323753c890078a9e7e791fee7470c3f99cc823d1a062205738b24a60c` |
| `updates/rtk_btusb.ko` | 70,508 B | `65468412dfea049864f8e6a477e7122649bf273bac5d73d4e9ed77919ee1dadd` |
| `rtl8733bu_fw` | 56,676 B | `e7980e8402a30af1355b942ffb6c3565ae41759405d566aa56844738237d2275` |
| `rtl8733bu_config` | 14 B | `2f9968b88d3f434fd67ffa00387fb7eaf0f04e2f9d04e6c5e22f39d359a53c4a` |

- `flange build rootfs -f`：通过；构建日志确认安装两份 firmware。最终 UBI
  可检出 `8733bu.ko`、`rtk_btusb.ko`、`rtl8733bu_fw`、
  `rtl8733bu_config` 与 `bluetoothd`。
- `rootfs.ubi`：227,540,992 B，SHA-256
  `56c85a137731c117167d68071f8dd4e6a45d84c61f740a839724b2381768284d`；
  小于 414 MiB rootfs partition（434,110,464 B）。
- `flange build boot -f` 与 `flange build image -f`：通过；最终仍使用 vendor FIT
  `boot.img` 与 SPI NAND 具名分区 bundle，没有引入 extlinux 或 raw GPT image。

## 实机验收

- 2026-07-14，用户刷入本次镜像后确认无线网卡已经正常出现；结合既有的
  `1a86:8091` / `0bda:b733` 枚举证据，RTL8733BUUA WiFi interface 已能完成
  driver binding 并注册 WLAN interface。
- 既有实机验收已确认 UART4/MSH console、RPMsg binary echo 与 ADB 可用。
- 尚未取得 2.4/5 GHz scan、测试 AP association/IP connectivity、Bluetooth HCI/
  discovery、reboot 自动恢复及 GMAC 完整回归证据；归档时保留这些限制，不将
  “WLAN interface 出现”扩展为未执行的功能验收。
