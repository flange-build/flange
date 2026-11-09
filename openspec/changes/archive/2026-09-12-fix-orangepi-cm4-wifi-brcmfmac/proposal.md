## Why

`orangepi-cm4` 实机（`orangepi-cm4-default-release`）启动后没有任何 WiFi 接口——`ip link` 只有 `lo` 与 `eth0`，`wlan0` 从不出现。

根因不是缺驱动，而是**驱动路线与部署固件的命名规范对不上**：内核同时编入了 Rockchip OOT `bcmdhd`（`menuconfig BCMDHD` 在 `rockchip_wlan/Kconfig` 中 `default y`，未被 defconfig 显式设置）与 mainline `brcmfmac`（`rockchip_linux_defconfig:668` 为 `=m`，经 SDIO MODALIAS 自动 modprobe）。实测 `brcmfmac` 先抢到 SDIO func，而 rootfs 里只有为 bcmdhd 部署的 `fw_bcm43456c5_ag.bin` / `nvram_ap6256.txt`，brcmfmac 要找的 `brcmfmac43456-sdio.{bin,txt,clm_blob}` 一个都没有，于是陷入死循环：

```
brcmfmac: brcmf_fw_alloc_request: using brcm/brcmfmac43456-sdio for chip BCM4345/9
brcmfmac mmc2:0001:1: Direct firmware load for brcm/brcmfmac43456-sdio.bin failed with error -2
brcmfmac: brcmf_sdio_htclk: HT Avail timeout (1000000): clkctl 0x50
mmc2: card 0001 removed
```

该循环约每 1.4 秒复现一次并持续占住 SDIO 总线，bcmdhd 因此永远拿不到设备（`lsmod` 中引用计数恒为 0），归档 change `2026-05-17-orangepi-cm4-bringup-wifi-and-npu-fix` 定下的 bcmdhd 路线实际从未生效，其 spec 中 "实机首启 WiFi 接口出现" 场景在实机上不成立。

本 change 把该板 WiFi 正式定为 **brcmfmac 路线**：AP6256 的 BCM43456 在 mainline brcmfmac 上支持完整，且 `radxa-pkg/radxa-firmware` 仓本就自带对应命名的三件套，无需引入新 source。已在实机验证通过（见下）。

## What Changes

- **BREAKING**（spec 层面）：`orangepi-cm4` 的 WiFi 驱动路线由 Rockchip OOT `bcmdhd` 改为 mainline `brcmfmac`。板级 kernel 行为与 `rootfs` 固件清单同步调整，用户态可见效果为 `wlan0` 由「不存在」变为「存在且可扫描」。
- `components/board/orangepi-cm4/config.jsonnet`：
  - `rootfs.+extra_firmware.files` 改为部署 brcmfmac 命名的 AP6256 三件套 `brcm/brcmfmac43456-sdio.bin`、`brcm/brcmfmac43456-sdio.txt`、`brcm/brcmfmac43456-sdio.clm_blob`，并保留 BT patchram `brcm/BCM4345C5.hcd`；移除仅 bcmdhd 使用的 `brcm/fw_bcm43456c5_ag.bin` 与 `brcm/nvram_ap6256.txt`。三个新文件与既有文件同在 `radxa-pkg/radxa-firmware` 仓 `lib/firmware/` 下，**不新增 source**。
  - `kernel.+config` 追加 `CONFIG_BCMDHD: 'n'`，关掉抢绑的 OOT 驱动（沿用 `armsom-cm5-io` / `atk-rk3506b` 既有写法）。`CONFIG_BRCMFMAC` 维持 defconfig 的 `=m`，board 不覆盖。
  - 更新 docstring：WiFi 段落由「走 SDIO 接 Rockchip OOT bcmdhd」改写为 brcmfmac 路线并记录抢绑踩坑。
- 删除 `components/board/orangepi-cm4/patches/kernel/0002-bcmdhd-set-fw-ampak-path-brcm.patch`——该 patch 只修 bcmdhd 的 `FW_AMPAK_PATH` 固件前缀，bcmdhd 关闭后成为由本次改动直接产生的孤儿代码。`0001` / `0003` / `0004` 编号与内容均不动（`builder/base.py:131` 按文件名 `sorted()` 应用，不要求连号）。
- 更新 spec `rockchip-orangepi-cm4`：重写 WiFi/BT 固件部署 requirement 的固件清单与驱动归属，新增「禁用 bcmdhd 避免 SDIO 抢绑」requirement，移除已失效的「修复 bcmdhd 固件搜索路径」requirement。
- 更新 `wiki/boards/orangepi-cm4.md` 与 `wiki/log.md`。

### 实机验证依据

在实机 `/lib/firmware/brcm/` 手工补入三件套后（仓库未改动，纯运行时验证）：

```
brcmfmac: brcmf_c_preinit_dcmds: Firmware: BCM4345/9 wl0: Feb 11 2020 11:54:51
          version 7.45.96.61 (be7af2d@shgit) (r745790) FWID 01-a41d86bd
3: wlan0: <NO-CARRIER,BROADCAST,MULTICAST,UP> ... link/ether c0:f5:35:41:28:96
```

`nmcli dev wifi list` 扫到 2.4G 与 5G 双频 AP（ch11 130 Mbit/s、ch161 540 Mbit/s），MAC 取自模组 OTP 而非 NVRAM 缺省值。仓库侧 `brcmfmac43456-sdio.txt` 首行为 `#AP6256_NVRAM_V1.1_08252017`，确认为本模组参数。

## 非目标

- **不改 BT**。`BCM4345C5.hcd` 保持部署，BT 走 `hci_uart`/`btbcm` 的链路本轮不动，也不预装 `bluez` 等用户态栈（延续归档 change 的边界）。
- **不引入 OOT 驱动编译**。不学 `armsom-cm5-io` 拉 `rkwifibt` 编外部 `bcmdhd.ko`——本板 brcmfmac in-tree 路线已验证可用，无需增加 `oot_sources` / `oot_modules`。
- **不动 DSI 屏、NPU、AMP**。`0001` / `0003` / `0004` 三条 patch 与 AMP product 配置原样保留。
- **不改 `builder/` 任何代码**。本 change 只用既有的 `rootfs.extra_firmware` 与 `kernel.config` 机制。
- **不动其它板**。`tspi-rk3566` 同款 `0002-bcmdhd-set-fw-ampak-path-brcm.patch` 属于该板自己的 bcmdhd 路线，不在本轮范围；跨板 patch 复用重构同样不做。
- **不配置 WiFi 自动连接**。本轮只保证「网卡存在、可扫描」，SSID/密码等产品级配网策略由产品方自取。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `rockchip-orangepi-cm4`：WiFi 契约由 bcmdhd 路线改为 brcmfmac 路线——固件清单换为 `brcmfmac43456-sdio` 三件套（含 CLM blob）、新增 `CONFIG_BCMDHD=n` 的驱动互斥约束、移除 `FW_AMPAK_PATH` patch requirement。BT、bootargs、NPU、AMP、base.dts 只读等其余 requirement 不变。

## Impact

- **修改文件**：
  - `components/board/orangepi-cm4/config.jsonnet`（`rootfs.extra_firmware.files`、`kernel.config`、docstring）
  - `openspec/specs/rockchip-orangepi-cm4/spec.md`（归档时由本 change 的 delta 落地）
  - `wiki/boards/orangepi-cm4.md`、`wiki/log.md`
- **删除文件**：
  - `components/board/orangepi-cm4/patches/kernel/0002-bcmdhd-set-fw-ampak-path-brcm.patch`
- **不动**：`builder/` 全部代码、其它 board / SoC / platform 配置、其它 spec、rockchip 平台层 `boot.py` / `kernel.py`、本板 `0001` / `0003` / `0004` patch。
- **运行时影响**：刷写后 `ip link` 出现 `wlan0` 且可扫描 2.4G/5G；`dmesg` 不再刷 `brcmfmac ... failed with error -2` 与 `HT Avail timeout`；SDIO 总线不再被反复 remove/re-probe。BT `hci0` 行为不变。镜像内不再有 bcmdhd 模块（约 1.3 MB）与两个 bcmdhd 专用固件。
- **构建影响**：删 patch + 加 `CONFIG_BCMDHD=n` 触发 orangepi-cm4 板 kernel 内容哈希变化，首次构建重编 kernel；`extra_firmware` 清单变化触发 rootfs 重组装。`radxa-firmware` 仓已在 `.build/sources/` 缓存，不产生新的 clone。
