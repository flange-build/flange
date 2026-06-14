## Why

`armsom-cm5-io` board 首版（`add-rk3576-armsom-cm5-io`）只做了裸机 bring-up（可构建、可启动、panfrost GPU），把 WiFi/BT 明确列为"留待后续独立变更"。本 change 补齐该板的无线链路：板载模组 **BW3752-50B1**（Iton，基于 **Broadcom BCM43752**，2T2R WiFi+BT combo，等价 AP6275S）通过 SDIO 接 WiFi、UART4 接 BT，但当前 rootfs 没有对应固件、bcmdhd 的 `FW_AMPAK_PATH` 也未启用，且 dts 的 `wifi_chip_type` 还停留在原型遗留的 `rtl8852bs`，导致 WiFi/BT 完全空载。

本 change 完全复用 `orangepi-cm4` 已验证的 Rockchip BSP SDIO WiFi/BT bring-up 模板（`rootfs.+extra_firmware` 拉三件套 + bcmdhd `FW_AMPAK_PATH` patch），把该板 WiFi/BT 硬件补到"开机就绪"。

## What Changes

- `components/board/armsom-cm5-io/config.py` 追加 `rootfs.+extra_firmware`：从 `radxa-pkg/radxa-firmware` 仓拉 BCM43752 / AP6275S 三件套 `brcm/fw_bcm43752a2_ag.bin`、`brcm/nvram_ap6275s.txt`、`brcm/BCM4362A2.hcd` → `/lib/firmware/`（三件套已在该仓 `lib/firmware/brcm/` 验证存在）。
- 新增两条 board 私有 kernel patch（按 board 各自一份，与既有 RK 板同类）：
  - `patches/kernel/0001-bcmdhd-set-fw-ampak-path-brcm.patch`：启用 `drivers/net/wireless/rockchip_wlan/rkwifi/bcmdhd/Makefile` 中的 `DHDCFLAGS += -DFW_AMPAK_PATH="\"brcm\""`，让 bcmdhd 在固件名前自动拼 `brcm/` 前缀（与 `orangepi-cm4` / `tspi-rk3566` 的 bcmdhd patch 一字不差）。
  - `patches/kernel/0002-dts-armsom-cm5-wifi-chip-ap6275s.patch`：把 `rk3576-armsom-cm5.dtsi` 中 `wireless-wlan` 的 `wifi_chip_type = "rtl8852bs"` 改为 `"ap6275s"`，与实物模组对齐（消除原型遗留）。
- 扩展 spec `rockchip-armsom-cm5-io`：新增"WiFi/BT 硬件就绪（BCM43752 / AP6275S 三件套到位、bcmdhd 固件路径打通、`wlan0` 可扫到 AP、BT 固件就绪可手动拉起 `hci0`）"契约。

## 非目标

- 不预装 BT 用户态栈（`bluez` / `bluetoothctl` / `btattach` 自启 unit 等）——本轮 BT 仅做"固件到位 + 硬件就绪"，`hci0` 由产品方自取用户态拉起；UART BT 的 patchram 加载不纳入本轮自动化。
- 不做 RF 性能调优——只锁定"能上电、能扫到 AP、`hci0` 可拉起"，`nvram_ap6275s.txt` 的天线/校准参数若与实板有漂移导致性能不达预期，留待后续按需换板级专属 nvram。
- 不引入 product / variant 维度（本轮只补无线，不分裂 lunch 矩阵）。
- 不引入 RTL8852BS 路线——这棵 argon BSP 树 `rockchip_wlan/` 仅含 `rkwifi`(bcmdhd)、无 RTL8852BS 源码，且实物为 Broadcom BCM43752，RTL 路线既无必要也无源码支撑。
- 不动 `builder/`、SoC 层 `rk3576/config.py`、其它 board / platform 配置。
- 不抽公共 patch 仓——沿用"板 patch 各自一份"现状。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `rockchip-armsom-cm5-io`：在首版裸机契约（可构建 / 可启动 / panfrost GPU）基础上**新增 WiFi/BT 硬件就绪 requirement**——锁定 BCM43752 / AP6275S 三件套到位、bcmdhd `FW_AMPAK_PATH=brcm` 路径打通、`wifi_chip_type` 与实物对齐、`wlan0` 可扫到 AP、BT 固件就绪可手动拉起 `hci0`。
  （`rockchip-armsom-cm5-io` 板级 capability 由 `add-rk3576-armsom-cm5-io` 引入；本 change 为其追加 WiFi/BT 行为，归档时合流到同一 board spec。）

## Impact

- **新增文件**：
  - `components/board/armsom-cm5-io/patches/kernel/0001-bcmdhd-set-fw-ampak-path-brcm.patch`
  - `components/board/armsom-cm5-io/patches/kernel/0002-dts-armsom-cm5-wifi-chip-ap6275s.patch`
- **修改文件**：
  - `components/board/armsom-cm5-io/config.py`（追加 `rootfs.+extra_firmware`、docstring 补 WiFi/BT 说明）
  - `wiki/boards/`（armsom-cm5-io 板级页：写实 WiFi/BT 方案与三件套来源）
- **不动**：所有 `builder/` 代码、SoC 层 `rk3576/config.py`、其它 board / platform 配置、其它 spec 文件。
- **运行时影响**：刷写后 `ip link` 出现 `wlan0`、`iw dev wlan0 scan` 能扫到周围 AP；`/lib/firmware/brcm/` 含三件套；BT 固件就绪（`BCM4362A2.hcd`），`hci0` 可由用户态手动拉起。GPU / 启动链路不受影响。
- **构建影响**：两条 kernel patch 触发 armsom-cm5-io 板 kernel 内容哈希变化，首次构建重编 kernel；`extra_firmware` 走 SourceManager 独立 clone 与 rootfs 组装，命中后续构建 cache。
