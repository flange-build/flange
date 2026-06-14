## Context

`armsom-cm5-io`（RK3576）首版只做裸机 bring-up，WiFi/BT 明确留作后续独立变更。现状（本 change 前实测/调研坐实）：

- **实物模组**：BW3752-50B1（Iton Technology），基于 **Broadcom BCM43752**，2T2R WiFi+BT combo，等价 AP6275S，亦用于 ArmSoM Sige5。WiFi 走 SDIO（`&sdio` `non-removable` `sd-uhs-sdr104` `sdmmc1m0` 引脚），BT 走 UART4（`ttyS4`）。
- **dts 现状**：`rk3576-armsom-cm5.dtsi` 的 `wireless-wlan` 节点 `wifi_chip_type = "rtl8852bs"` 是原型遗留（CM5 工程样机曾用 RTL8852BS）；`wireless-bluetooth` / `&sdio` / `&uart4` 节点齐全且 `status = "okay"`。
- **驱动现状**：base `rockchip_linux_defconfig` 已 `CONFIG_WL_ROCKCHIP=y`、`CONFIG_RFKILL_RK=y`；但树内 `drivers/net/wireless/rockchip_wlan/` **仅含 `rkwifi`(bcmdhd)**，无 RTL8852BS 源码，mainline `rtw89` 也只有 PCIe 的 `RTW89_8852CE`。即：这棵 argon BSP 树只能编出 bcmdhd（Broadcom/Synaptics 系），编不出 RTL。
- **固件现状**：rootfs 无任何 BCM43752 固件；bcmdhd `FW_AMPAK_PATH`（`drivers/net/wireless/rockchip_wlan/rkwifi/bcmdhd/Makefile` 第 394 行）默认注释关闭，导致拼出的固件名缺 `brcm/` 前缀。

`orangepi-cm4`（RK3566 + AP6256/BCM4345C5）的归档 change `2026-05-17-orangepi-cm4-bringup-wifi-and-npu-fix` 是 flange 处理 Rockchip BSP SDIO WiFi/BT 的黄金模板，本 change 直接复用。

## Goals / Non-Goals

**Goals:**

- `armsom-cm5-io-default-release` rootfs 含 BCM43752 / AP6275S 三件套，bcmdhd 固件加载路径打通，实机 `wlan0` 可扫到 AP。
- BT 固件（`BCM4362A2.hcd`）就绪，`hci0` 可由用户态手动拉起。
- dts `wifi_chip_type` 与实物对齐（`ap6275s`），消除原型遗留。
- 改动仅集中在 `components/board/armsom-cm5-io/`，不触发任何 `builder/` 修改。

**Non-Goals:**

- 不预装 BT 用户态栈（`bluez` / `btattach` 自启 unit）；UART BT patchram 自动加载不在本轮。
- 不做 RF 性能调优（nvram 漂移留待后续按需换板级专属 nvram）。
- 不引入 product / variant 维度。
- 不引入 RTL8852BS 路线（无源码、与实物不符）。
- 不动 `builder/` / SoC 层 `rk3576/config.py` / 其它 board / platform 配置。
- 不抽公共 patch 仓（沿用"板 patch 各自一份"）。

## Decisions

### Decision 1：WiFi/BT 走 bcmdhd（Broadcom），不走 RTL

实物为 Broadcom BCM43752，且这棵树 `rockchip_wlan/` 仅含 bcmdhd（无 RTL8852BS 源码）。dts 里 `rtl8852bs` 是原型遗留，必须改成 `ap6275s` 与实物对齐。

**理由**：双向印证——硬件是 Broadcom 系（bcmdhd 路线），树里也只有 bcmdhd 可编。RTL 路线需额外引入 Rockchip rkwifibt OOT 的 RTL8852BS 驱动 + Kconfig + Makefile，既无必要也工程量大。

### Decision 2：固件源选 radxa-firmware（与 cm4 / tspi 同源同机制）

`radxa-pkg/radxa-firmware` 仓 `lib/firmware/brcm/` 已确认含 `fw_bcm43752a2_ag.bin` / `nvram_ap6275s.txt` / `BCM4362A2.hcd`（本地多个变更已 clone 验证）。board 层 `rootfs.+extra_firmware` 一条目（`repo_subdir=radxa-firmware/lib/firmware`、`dest=lib/firmware`、`files=[三件套]`），走 `SourceManager.ensure_extra_firmware`。

**理由**：与 `orangepi-cm4`（AP6256）、`radxa-zero` 等同仓同机制，零新增 source 机制。BCM43752 的 BT 子系统固件就是 `BCM4362A2.hcd`（Broadcom 命名习惯，BT 与 WiFi 子系统各自编号），armbian 对该板也用同一文件，互相印证。

### Decision 3：仅两条 board 私有 kernel patch，比 cm4 更精简

- `0001-bcmdhd-set-fw-ampak-path-brcm.patch`：与 cm4/tspi 的 bcmdhd patch **一字不差**（同一文件、同一行：`bcmdhd/Makefile` 取消 `FW_AMPAK_PATH` 注释并设 `brcm`）。
- `0002-dts-armsom-cm5-wifi-chip-ap6275s.patch`：改 `rk3576-armsom-cm5.dtsi` 的 `wifi_chip_type` `rtl8852bs` → `ap6275s`。

**不需要** cm4 的 `0001-bootargs-fix`（cm5 dtsi 无 `chosen.bootargs` 硬编码 `root=`，已确认）、**不需要** `0003-disable-rknpu`（RK3576 首版已正常起 rootfs，无 NPU PD panic）。

**理由**：patch 文件按 board 隔离编入 kernel 源码树，与既有 RK 板隔离方式一致；cm5 比 cm4 干净，只保留无线必需的两条。

### Decision 4：扩展 `rockchip-armsom-cm5-io` board spec，不新建 capability

本 change 是给同一块板追加 WiFi/BT 行为，沿用 cm4 的 per-board 单 spec 惯例，对首版引入的 `rockchip-armsom-cm5-io` capability 追加 ADDED Requirements，归档时合流。

**理由**：board 级契约单文件治理，与 `rockchip-orangepi-cm4` 风格一致。首版 spec 尚未归档，本 change 与首版 change 各持 delta，归档顺序决定基线/增量合并。

## Risks / Trade-offs

- **[CONFIG_BCMDHD 是否实际编出]** base defconfig 仅见 `CONFIG_WL_ROCKCHIP=y`（总开关），未见显式 `CONFIG_BCMDHD=m/y`。bcmdhd 是否随 `WL_ROCKCHIP` 编出需在 tasks 阶段实测（`.build` 内核 `.config` / 产物 `bcmdhd.ko`）。**Mitigation**：tasks 列明验证项；若未编出，按需补一条 board defconfig fragment（`CONFIG_BCMDHD=m`），不影响本 change 其余结构。
- **[BT hci0 不自动出现]** UART BT 需用户态 patchram 加载（`brcm_patchram_plus` / `btattach`），本轮不预装。**Mitigation**：spec 只锁"固件就绪 + 可手动拉起"，与 Non-Goal 一致；armbian 侧用 `brcm_patchram_plus` + service 的做法留作未来 BT 用户态化的参考。
- **[nvram 天线/校准漂移]** `nvram_ap6275s.txt` 为 radxa 通用参数，与 ArmSoM CM5 实板若有差异可能 RF 性能不达预期。**Mitigation**：spec 只锁"能上电、能扫到 AP"，性能调优不在本轮 SLA；后续可在 `files` 项加 `src`→`dest` rename 拉板级专属 nvram。
- **[与首版 change 的 spec 合并顺序]** 两个未归档 change 同持 `rockchip-armsom-cm5-io` delta。**Mitigation**：先归档首版建基线、再归档本 change 作增量；`openspec validate --strict` 在归档阶段校验。
