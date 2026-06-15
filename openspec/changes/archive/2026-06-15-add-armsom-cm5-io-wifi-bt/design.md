## Context

`armsom-cm5-io`（RK3576）首版只做裸机 bring-up，WiFi/BT 留作后续独立变更。现状：

- **实物模组**：BW3752-50B1（Iton），基于 **Broadcom BCM43752**（chip id 0xaae8 rev2），2T2R WiFi6+BT5.3 combo，等价 AP6275S，亦用于 ArmSoM Sige5。WiFi 走 SDIO（`&sdio` `non-removable` `sdmmc1m0`），BT 走 UART4（`ttyS4`）。
- **dts**：`rk3576-armsom-cm5.dtsi` 的 `wireless-wlan` 节点 `wifi_chip_type = "rtl8852bs"` 是工程样机遗留；`wireless-bluetooth` / `&sdio` / `&uart4` 节点齐全。

### 调试根因（实机坐实）

首版裸机镜像里 WiFi 不可用（wlan0 存在但扫不到任何 AP、nmtui 无设备），系统排查定位到两个独立根因：

1. **驱动冲突**：base `rockchip_linux_defconfig` 同时开了内建 `CONFIG_BCMDHD=y`（Rockchip OOT bcmdhd 内建形态）和 mainline `CONFIG_BRCMFMAC=m`。两者都认 BCM43752 SDIO 设备——brcmfmac 先 bind func1、加载失败（无 mainline 格式固件）、`brcmf_sdio_htclk: HT Avail timeout` 污染芯片 SDIO 状态，bcmdhd 虽接管 func2 注册了 wlan0 但功能异常。
2. **CLM blob 缺失**：radxa-firmware 仓只有 `fw/nvram`、**无 `clm_bcm43752a2_ag.blob`**。固件内置 `Generic.Min` CLM 不接受 set country（`dhd_conf_set_country: country setting failed -2`，试 CN/US 均失败）→ 无可用信道 → 扫描空。实机补上 CLM blob 后 `country CN` 成功、`CLM: 9.9.8_SS`、扫到 2.4G+5G AP。

`radxa-rock5b`（RK3588 + M.2 RTL8852BE）的 rkwifibt OOT 模式（`oot_sources` + `+oot_modules` + `+extra_firmware(source=oot:...)`) 是 flange 编 OOT WiFi 驱动的机制模板，本 change 复用到 BCM43752。

## Goals / Non-Goals

**Goals:**

- `armsom-cm5-io` 用 rkwifibt OOT bcmdhd 驱动 + AP6275S 固件（含 CLM），实机 `wlan0` 扫到 AP、`country` 设置成功、nmtui 可见可连。
- 根除 brcmfmac 与内建 bcmdhd 的驱动冲突。
- BT 固件（`BCM4362A2.hcd`）就绪，`hci0` 可由用户态手动拉起。
- 改动仅集中在 `components/board/armsom-cm5-io/`，不触发 `builder/` 修改。

**Non-Goals:**

- 不预装 BT 用户态栈（`bluez`/`btattach`）；UART BT patchram 自动加载不在本轮。
- 不做 RF 性能调优（nvram 漂移留待后续按需换板级专属 nvram）。
- 不引入 product/variant 维度。
- 不动 `builder/` / SoC 层 `rk3576/config.py` / 其它 board/platform 配置。

## Decisions

### Decision 1：WiFi 走 rkwifibt OOT bcmdhd（对齐 rock5b），关内建驱动

`kernel.oot_sources.rkwifibt` = `https://github.com/radxa/rkwifibt.git` develop（与 rock5b/orangepi-5-plus 同 repo 同分支）。`+oot_modules` 编 `drivers/bcmdhd` 出 `bcmdhd.ko`。`+defconfig` 关内建 `# CONFIG_BCMDHD is not set`（与 OOT 同名冲突）+ `# CONFIG_BRCMFMAC is not set`（抢芯片，见 Context 根因 1）。

**理由**：用户明确选 OOT 路线对齐项目惯例；关 brcmfmac 根治冲突。内建 bcmdhd 关掉后由 OOT module 形态接管（装 `/lib/modules/<rel>/updates/bcmdhd.ko`，靠 SDIO MODALIAS 自动 modprobe）。

### Decision 2：OOT bcmdhd 编译绕过 `bcmdhd_sdio` target，直接 `-C/M=`

`make_args = [-C {kernel_src}, M={rkwifibt_src}/drivers/bcmdhd, modules, CONFIG_BCMDHD=m, CONFIG_BCMDHD_SDIO=y, ARCH=arm64, CROSS_COMPILE=...]`。

**理由**：bcmdhd Makefile 的 `bcmdhd_sdio` target 内部硬编码 `make -C $(LINUXDIR) M=$(PWD)`，而 flange 容器里 `$(PWD)=/workspace`（非 bcmdhd 目录），导致 `M=` 指错、编译失败。bcmdhd Makefile 有无条件 `obj-m += $(MODULE_NAME).o`，直接用 kernel kbuild 的 external module 机制（显式 M=）绕过 PWD 依赖——与 rock5b rtl8852be 显式传 M= 同理。

### Decision 3：固件从 rkwifibt 仓部署（含 CLM blob）

`rootfs.+extra_firmware`：`source="oot:rkwifibt"`、`repo_subdir=firmware/broadcom/AP6275S`，部署 `wifi/{fw_bcm43752a2_ag.bin, nvram_ap6275s.txt, clm_bcm43752a2_ag.blob}` + `bt/BCM4362A2.hcd` → `lib/firmware/brcm`。

**理由**：**CLM blob 只有 rkwifibt 仓有**（radxa-firmware / linux-firmware / armbian 均无），是 country 设置成功、扫到 AP 的关键（见 Context 根因 2）。复用 `kernel.oot_sources` 已 ensure 的同一 rkwifibt 源，零新增 source。

### Decision 4：OOT bcmdhd 固件路径用 modprobe.d module param 覆盖

board overlay `overlay/etc/modprobe.d/bcmdhd.conf`：`options bcmdhd firmware_path=/lib/firmware/brcm/fw_bcmdhd.bin nvram_path=/lib/firmware/brcm/nvram.txt`。

**理由**：rkwifibt OOT bcmdhd 编译默认 `CONFIG_BCMDHD_FW_PATH=/vendor/etc/firmware/`（Android 路径，Makefile 438-443），与 flange 固件落点 `/lib/firmware/brcm/` 不匹配 → 实机 `download failed`、wifi 起不来。bcmdhd 支持 `firmware_path`/`nvram_path` module param（`module_param_string`），经 SDIO MODALIAS 自动 modprobe 时读 modprobe.d options 覆盖。给通用名 `fw_bcmdhd.bin`/`nvram.txt`，bcmdhd `CONFIG_BCMDHD_AUTO_SELECT` 按 chip 拼成实际名 `fw_bcm43752a2_ag.bin`/`nvram_ap6275s.txt`、clm 同目录推导——实机实测开机自动加载即命中、country CN、扫到 AP。

**备选**：编译传 `CONFIG_BCMDHD_FW_PATH`（Makefile `ifeq 空才设默认`逻辑下传非空值反而不 `-D` 出，无效）；固件部署到 `/vendor/etc/firmware/`（Android 路径污染标准 rootfs）。均否决。

### Decision 5：保留 dts `wifi_chip_type` patch + 扩展 board spec

`patches/kernel/0001-dts-armsom-cm5-wifi-chip-ap6275s.patch` 把 `wifi_chip_type` `rtl8852bs`→`ap6275s`（实机确认 `wlan_platdata: wifi_chip_type = ap6275s` 生效）。spec 沿用 cm4 per-board 单 spec 惯例，对 `rockchip-armsom-cm5-io` capability 追加 ADDED Requirements。

## Risks / Trade-offs

- **[OOT 固件路径依赖 modprobe.d 时序]** bcmdhd 经 udev SDIO MODALIAS 自动 modprobe，读 `/etc/modprobe.d/` options。**Mitigation**：实机 reboot 实测——开机 [8.2s] bcmdhd 自动带 `firmware_path` 加载、固件命中、country CN、扫到 AP，时序成立。
- **[BT hci0 不自动出现]** UART BT 需用户态 patchram（`brcm_patchram_plus`/`btattach`），本轮不预装。**Mitigation**：spec 只锁"固件就绪 + 可手动拉起"。
- **[出现 wlan1 双接口]** 实机 `nmcli dev status` 见 wlan0 + wlan1（bcmdhd dual STA/AP virtual interface）。**Mitigation**：wlan0 可用、扫到 AP，wlan1 不影响首版验收；如需精简后续调 bcmdhd `op_mode`/iface 参数。
- **[nvram 天线/校准漂移]** `nvram_ap6275s.txt` 为 rkwifibt 通用参数。**Mitigation**：spec 只锁"能扫到 AP"，性能调优不在本轮 SLA。
- **[与首版 change 的 spec 合并顺序]** 两个未归档 change 同持 `rockchip-armsom-cm5-io` delta。**Mitigation**：归档顺序决定基线/增量，`openspec validate --strict` 校验。
