## Why

`armsom-cm5-io` board 首版（`add-rk3576-armsom-cm5-io`）只做了裸机 bring-up，把 WiFi/BT 明确列为"留待后续独立变更"。本 change 补齐无线链路：板载模组 **BW3752-50B1**（Iton，基于 **Broadcom BCM43752**，2T2R WiFi6+BT5.3 combo，等价 AP6275S）通过 SDIO 接 WiFi、UART4 接 BT。

首版裸机镜像里 WiFi 实测不可用（wlan0 存在但扫不到任何 AP），系统排查定位到两个根因：① mainline `brcmfmac`(=m) 与内建 `bcmdhd`(=y) 争抢 BCM43752 SDIO 芯片（brcmfmac 先 bind、HT timeout 污染芯片状态）；② CLM blob 缺失致 `set country failed`、无可用信道。本 change 改走 **rkwifibt OOT bcmdhd 路线**（对齐 `radxa-rock5b`），关掉冲突的内建驱动、从 rkwifibt 仓部署含 CLM 的完整固件，实机验证 country CN 成功、扫到 2.4G+5G AP。

## What Changes

- `components/board/armsom-cm5-io/config.py`：
  - `kernel.oot_sources.rkwifibt` = `https://github.com/radxa/rkwifibt.git` develop（与 rock5b/orangepi-5-plus 同 repo 同分支）。
  - `kernel.+oot_modules`：编 `drivers/bcmdhd` 出 OOT `bcmdhd.ko`（`-C {kernel_src} M=.../bcmdhd modules CONFIG_BCMDHD=m CONFIG_BCMDHD_SDIO=y`）。
  - `kernel.+defconfig`：关内建 `# CONFIG_BCMDHD is not set`（与 OOT 同名冲突）+ `# CONFIG_BRCMFMAC is not set`（抢芯片）。
  - `rootfs.+extra_firmware`：`source="oot:rkwifibt"` 从 `firmware/broadcom/AP6275S` 部署 `wifi/{fw,nvram,clm}` + `bt/BCM4362A2.hcd` → `/lib/firmware/brcm/`。
- 新增 board overlay `overlay/etc/modprobe.d/bcmdhd.conf`：用 `firmware_path` module param 把 OOT bcmdhd 固件路径从默认 `/vendor/etc/firmware/`（Android）覆盖到 `/lib/firmware/brcm/`。
- 新增 board patch `patches/kernel/0001-dts-armsom-cm5-wifi-chip-ap6275s.patch`：`wifi_chip_type` `rtl8852bs`→`ap6275s`（与实物对齐）。
- 扩展 spec `rockchip-armsom-cm5-io`：新增 WiFi/BT OOT 链路就绪契约。

## 非目标

- 不预装 BT 用户态栈（`bluez`/`bluetoothctl`/`btattach`）——本轮 BT 仅"固件到位 + 硬件就绪"，`hci0` 由产品方自取用户态拉起。
- 不做 RF 性能调优——只锁"能扫到 AP"，`nvram_ap6275s.txt`（rkwifibt 通用参数）若与实板漂移导致性能不达预期，留待后续换板级专属 nvram。
- 不引入 product/variant 维度。
- 不动 `builder/` / SoC 层 `rk3576/config.py` / 其它 board/platform 配置。
- 不抽 SoC 家族中间层（与 rock5b deep_merge 重复 OOT 字段可接受，待第三块同类板再评估）。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `rockchip-armsom-cm5-io`：在首版裸机契约（可构建/可启动/panfrost GPU）基础上**新增 WiFi/BT OOT 链路就绪 requirement**——rkwifibt OOT bcmdhd 驱动 + 关内建 bcmdhd/brcmfmac、AP6275S 固件含 CLM 部署、modprobe.d 固件路径覆盖、dts `wifi_chip_type` 对齐、实机 `wlan0` 扫到 AP / country 设置成功。
  （`rockchip-armsom-cm5-io` capability 由 `add-rk3576-armsom-cm5-io` 引入；本 change 追加 WiFi/BT，归档时合流。）

## Impact

- **新增文件**：
  - `components/board/armsom-cm5-io/patches/kernel/0001-dts-armsom-cm5-wifi-chip-ap6275s.patch`
  - `components/board/armsom-cm5-io/overlay/etc/modprobe.d/bcmdhd.conf`
- **修改文件**：
  - `components/board/armsom-cm5-io/config.py`（oot_sources/+oot_modules/+defconfig/+extra_firmware + docstring）
  - `wiki/boards/armsom-cm5-io.md`（新建/写实 WiFi/BT 方案与调试踩坑）
- **不动**：所有 `builder/` 代码、SoC 层 `rk3576/config.py`、其它 board/platform 配置。
- **运行时影响**：刷写后 OOT bcmdhd 经 SDIO MODALIAS 自动加载（读 modprobe.d 固件路径），`ip link` 出现 `wlan0`、`nmcli dev wifi list` 扫到 AP、country CN 成功；BT 固件就绪可手动拉起 `hci0`。
- **构建影响**：`oot_sources` 触发 rkwifibt clone + OOT bcmdhd 编译；`+defconfig` 关内建驱动触发 kernel 重编一次；overlay/extra_firmware 走 rootfs 组装。
