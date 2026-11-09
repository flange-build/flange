---
title: radxa-dragon-q6a
type: board
status: wip
sources:
  - components/board/radxa-dragon-q6a/config.jsonnet
  - components/platform/qualcommqcs6490/qcs6490/config.jsonnet
  - components/platform/qualcommqcs6490/patches/kernel/0001-dwc3-gadget-preserve-pending-requests-on-clear-stall.patch
  - components/platform/qualcommqcs6490/patches/kernel/0002-dts-radxa-dragon-q6a-usb1-peripheral-for-adb.patch
  - components/platform/qualcommqcs6490/patches/kernel/0003-dts-radxa-dragon-q6a-i2c13-drop-gsi-dma-for-panel.patch
  - components/platform/qualcommqcs6490/patches/kernel/0004-feat-radxa-common-kernel-config.patch
  - components/platform/qualcommqcs6490/patches/kernel/0005-feat-radxa-custom-kernel-config.patch
  - components/platform/qualcommqcs6490/patches/kernel/0006-i2c-geni-force-fifo-on-gsi-mismatch.patch
  - components/platform/qualcommqcs6490/patches/kernel/0007-dts-radxa-dragon-q6a-i2c10-drop-gsi-dma.patch
  - components/platform/qualcommqcs6490/patches/aic8800/0001-cfg80211-get-tx-power-6.18-signature.patch
  - components/platform/qualcommqcs6490/patches/aic8800/0002-in-irq-removed-linux-6.10.patch
  - components/packages/meizu-e3-panel/package.py
  - builder/platforms/qualcommqcs6490/
  - builder/flash/strategy.py
  - builder/source.py
  - openspec/changes/add-qcs6490-radxa-dragon-q6a/
  - openspec/changes/archive/2026-05-31-migrate-qcs6490-kernel-702/
  - openspec/changes/archive/2026-09-27-fix-qcs6490-i2c10-fifo-el2/
  - openspec/changes/archive/2026-09-28-enable-q6a-auto-el2/
  - docs/first-steps.md
related:
  - "[[qualcommqcs6490 平台]]"
  - "[[radxa-cubie-a7a]]"
  - "[[FlashStrategy 抽象]]"
  - "[[meizu-e3-panel]]"
  - "[[硬件特性包]]"
  - "[[构建期 dtb overlay 合并]]"
updated: 2026-09-28
---

> 阅读前提：先完成[初学指南](../../docs/first-steps.md)的环境准备，运行
> `flange target list radxa-dragon-q6a` 确认当前目标，再按该型号硬件说明匹配介质、接口与下载模式。
> 本页是配置摘要与硬件记录；下文验收只覆盖记录的版本、产品和测试项，不代表当前全部组合已实测。
> [返回板卡索引](index.md) · [构建与刷写流程](../workflows/lunch-build-flash-流程.md)

## TL;DR

Radxa Dragon Q6A，Qualcomm QCS6490 (SC7280-class) 单板，128 GB Samsung KLUDG4UHGC-B0E1 UFS，板载 RTL8168 PCIe 千兆 + AIC8800 D80 USB Wi-Fi/BT 模组（与 [[radxa-cubie-a7a]] 同款）。flange 首个 Qualcomm 板，验证 UEFI/GRUB + EDL 刷写 + Adreno 643 freedreno 全栈。

> ⚠️ **内核基线：vendor BSP 6.6.90 → mainline 6.18.2（2026-05-30）→ mainline 7.0.2（2026-05-31，当前，见下节）**。本页部分章节（魅族屏 / 9 个坑 / AIC8800 路径等）是早期记录，部分需在 7.0.2 重验。

## 内核基线：mainline 7.0.2（2026-05-31，rsdk 对齐，当前）

继 6.18.2 后再升 **`radxa/kernel@linux-7.0.2`**，pin commit `7473a9f`（= radxa `linux-qcom` 7.0.2-2 子模块；`linux-7.0.2` 分支 tip 会回归 UFS 复位，故固定）。

**config 对齐 rsdk 四段**（`qcs6490/config.jsonnet` defconfig）：`defconfig qcom_module.config radxa.config radxa_custom.config`（同 radxa `.github/local/Makefile.local`）。`qcom_module.config`（软链 `radxa_qcom_7_0_defconfig`）是 qcom 全量平台 config——补齐 `QCOM_AOSS_QMP`/`LLCC`/`ARM_SMMU_V3`/`QSEECOM`/UFS 等数百项 `=y`。额外 symbol 全部收敛到 `kernel.config`。

**⚠️ UFS 开机整机复位（QHEE `PM: Reset by PSHOLD`）双根因 + 修复**：① 早期只用 `defconfig radxa.config`、漏 `qcom_module.config` → UFS probe 缺 qcom 平台驱动；② **板上 SPI 固件过旧**（`251013`/00364-KODIAKLA），与 7.0.2 `kodiak` DTB 资源/握手不匹配。两者都必修——补四段 config + `flange flash --spi-firmware` 刷 `260120`/00549-KODIAKWP。⚠️ `flange flash` 默认只刷 UFS、**不碰 SPI**，大版本内核/DTB 迁移极易漏固件。决策档见 openspec `migrate-qcs6490-kernel-702`。

**硬件编码 = 可用（真根因＝UEFI Hypervisor Override，2026-06-01 修正）**：此前"喂帧即整机复位"的根因是 **UEFI `Hypervisor Settings → Hypervisor Override` 未开 → 系统以 EL1 启动（无 Gunyah hypervisor）→ 编码器访问 CP/secure 内存 fault → 复位**，并非固件/TZ/驱动。开机 F2 进 UEFI 开启后系统以 **EL2** 启动（`/dev/kvm` 出现、`/dev/mtd0` 消失），**flange 现有 mainline 7.0.2 venus + 通用固件直接编码通过**（`v4l2h264enc` 720p→6.46MB 有效 H264、零复位）。2026-09-28 起 flange 默认进 EL2，无需进 UEFI 修改，见下文「默认 EL2」。见下表编码行。

**EL2 启动与 GPI DMA（2026-09-27）**：`260120` 固件开启 `Hypervisor Override` 后，Radxa UEFI 在 ExitBootServices 前**自行**给 GRUB `devicetree` 加载的 flange DTB 打 KVM fixup：`/chosen` 加 `radxa,enable-kvm`、`radxa,dtb-fixup-applied`，并套用内核源里 `qcs6490-radxa-dragon-q6a-kvm.dtso` 的内容（GPU zap 禁用、scm `shm-bridge-vmid`、venus 追加 iommus 与 `video-firmware`、PCIe ranges、adsp/cdsp `qcom,broken-reset`），另有 PCIe iommu-map 等平台 fixup。因此 flange 无需像 [[thundercomm-rubikpi3]] 那样自带 el2 dtso。EL2 下 `i2c10`（RTC，原 DT 声明 `qcom,enable-gsi-dma`）申请 GPI 通道时，`gpi_config_interrupts()` 读 gpii 1 的 `GPII_n_CNTXT_MSI_BASE_LSB` 触发同步外部中止（`ESR 0x96000010`，另一次为异步 SError panic）。同页前序寄存器可访问，属于寄存器级访问控制。udev 加载 `i2c_qcom_geni` 即崩溃复位，GRUB 追加 `module_blacklist=i2c_qcom_geni` 可绕过。修复：`patches/kernel/0007` 删 `i2c10` 的 flag，由 `0006` 重 provision 回 FIFO。现在 Q6A 所有启用的 i2c 都走 FIFO、不使用 GPI。EL2 实板验证通过（2026-09-27，default-debug）：不加启动参数启动到 rootfs，`/proc/interrupts` 无 `gpi-dma`，RTC（`rtc-ds1307` 驱动 m41t11，`rtc0`）读写走时正常。EL1 下（`Hypervisor Override` 关闭，meizu-e3-bringup-debug，同日）i2c 同样正常：i2c10/i2c13 走 FIFO、无 `gpi-dma`，RTC 开机 hctosys 与宿主时间一致，`sec_ts` probe 读到 `AC,6F,70`。meizu-e3-bringup-debug 在 EL2 下同日回归通过：`card1-DSI-1` `connected`/`enabled` @ 1080×2160；`sec_ts` device id `AC,6F,70`，触摸 5 次按下、419 个输入事件、坐标连续（中断 193→304）；`sgm37604a` 背光写 1024/2048 读回一致；i2c13 无 `GPI transfer failed`，`gpi-dma` 中断为 0。change `fix-qcs6490-i2c10-fifo-el2`。

**默认 EL2（2026-09-28）**：Radxa UEFI 的 `Hypervisor Override` 出厂为 `Auto`，依据 Linux 设备树
`/chosen/radxa,enable-kvm` 决定是否进 EL2（UEFI 字符串“Auto: Auto enable or disable based on Linux DeviceTree”），
DSP 预加载的 `Auto` 也是「以 EL2 启动时预加载」。Radxa 官方开启 KVM 的方式是 rsetup 叠加内核自带的
`qcs6490-radxa-dragon-q6a-kvm.dtso`（`radxa,enable-kvm = <1>` 加 GPU zap、ADSP/CDSP `qcom,broken-reset`、SCM
SHM bridge、venus `video-firmware`、PCIe 窗口修正）。flange 据此把 `device_tree.name` 改为内核 Makefile 构建的组合 DTB
`qcs6490-radxa-dragon-q6a-kvm`（base + 该 overlay），`meizu-e3-bringup` 的面板 overlay 叠加在它之上，不复制
overlay 内容。UEFI 保持 `Auto`（或 `Enabled`）即进 EL2，DSP 与硬件编码同时可用；**不支持 `Disabled`**：EL1 下
这份 DTB 的 zap 禁用与 venus 非 TZ 启动会使 GPU 与视频不可用。实板（meizu-e3-bringup-debug，`Auto`）用户验证通过。
change `enable-q6a-auto-el2`。

**EL2 下 ADSP / CDSP（2026-09-27 实板，meizu-e3-bringup-debug）**：EL2 下两个 DSP 都可用。它们在进入 Linux 前已由启动固件拉起，内核 `qcom_q6v5_pas` 只做接管（attach）：`remoteproc0` adsp、`remoteproc1` cdsp 的 `state` 为 `attached`，`firmware` 为 `unknown`，rootfs 里的 `qcom/qcs6490/radxa/dragon-q6a/{adsp,cdsp}.mbn` 开机不会被加载。[[thundercomm-rubikpi3]] 不同：它在 EL2 下由内核自己经 PAS 加载 DSP，卡在 TZ 不支持 `PAS_GET_RSCTABLE`。实板证据：

- glink 通道：ADSP 有 `IPCRTR`、`fastrpcglink-apps-dsp`、`adsp_apps`；CDSP 有 `IPCRTR`、`fastrpcglink-apps-dsp`、`cdsprmglink-apps-dsp`、`cvp-glink-apps-dsp`。
- QRTR 名字服务：ADSP（node 5）发布 7 个 QMI 服务，CDSP（node 10）发布 5 个，都含 SSCTL（43）和 servreg notifier（66）；本机 `qcom_pd_mapper` 发布 servreg locator（64）。
- FastRPC：`/dev/fastrpc-adsp`、`/dev/fastrpc-cdsp`、`/dev/fastrpc-cdsp-secure` 均存在。`FASTRPC_IOCTL_GET_DSP_INFO` 经 DSP utilities handle 与 DSP 实际往返：ADSP 为 Hexagon v66（`ARCH_VER 0xc666`）；CDSP 为 v68（`0x8a68`），HVX 128B ×2、VTCM 2 MiB ×1、HMX（depth 32 / spatial 64）、支持异步 RPC。两者 `FASTRPC_IOCTL_INIT_ATTACH`（root PD）均返回 0，dmesg 无新错误。开机的 `no reserved DMA memory for FASTRPC` 只是提示，驱动改用默认 DMA 池。rootfs 未装 libadsprpc、QNN 等用户态，目前还不能直接跑模型推理。
- 未验证：`recovery=enabled`，但 DSP 崩溃后恢复要由内核经 PAS 重新加载，EL2 下能否成功未测；参照 RUBIK Pi 3 的结果，很可能失败。
- 音频：ADSP 上的 GPR 服务 APM（2:1）、PRM（2:2）已注册，LPASS VA/RX/TX macro 拿到 PRM 时钟，两路 SoundWire 枚举到 WCD938x。但开机 9.7 s 有一次 `qcom-apm gprsvc:service:2:1: CMD timeout for [1001021] opcode`（`APM_CMD_GET_SPF_STATE`），随后声卡因缺少 topology `qcom/qcs6490/QCS6490-Radxa-Dragon-Q6A-tplg.bin`（-2）实例化失败，`/proc/asound/cards` 为空。音频链路要补上 topology 后再验证。

**⚠️ 魅族 DSI 屏偶发黑屏（2026-09-27，与 EL 无关，待查）**：meizu-e3-bringup 曾出现一次只有背光、没有画面，fbdev 彩条和 `modetest -s 34@70` 都不显示。当时是 EL1，一度误判为 EL1 限制；之后实测 EL1 也能正常显示，现象更像面板初始化时复位没有生效。黑屏时 Linux 侧各层均无异常：DRM 原子状态中 plane-0 挂 fb、crtc-0 active、DSI-1 connected；encoder-0 vsync 持续计数、underrun 为 0；面板 `enable` 的 2 条 DCS 命令（`exit_sleep_mode`、`set_display_on`）对应 `dsi_isr` 2 次、无报错；SMMU fault 中断为 0。也就是说，驱动认为命令发出去了，但面板没有进入显示状态。相关时序见 `panel_meizu_e3.c` 的 `meizu_e3_prepare()`：复位脚 `tlmm 44`（active-low）拉低 20 ms 后释放、等 120 ms；而 overlay 里 `vcc_3v3_lcd` 为 `regulator-always-on`/`regulator-boot-on`（为让 `sec_ts` 先上电），`prepare` 中的 `regulator_enable` 不会真正给面板重新上电，面板能否回到干净状态只取决于这一次复位脉冲，热重启时尤其可疑。已知线索（未完成复现）：用户观察热重启比冷启动更容易黑屏；面板 1.8V vccio（`vreg_l1c_1p8`）同时供两个 USB PHY，热重启期间很可能不断电，而 3.3V 由 `gpio80`（pull-down）控制、热复位时大概率掉电，冷/热启动的上电顺序因此不同；同一次启动内（显示正常时）`fb0` blank/unblank 走一遍 disable→unprepare→prepare→enable 后画面能恢复，blank 时出现 `dsi_err_worker: status=5`（`TIMEOUT|FIFO`）。注意 `adb reboot` 在本板返回 `error: closed` 不会重启，热重启试验需在 shell 内执行 `systemctl reboot`。

## 内核基线：mainline 6.18.2（2026-05-30，前一步）

## 内核基线：mainline 6.18.2（2026-05-30 迁移）

**动机**：原 vendor BSP `kernel.qclinux.1.0.r1-rel`(6.6.90) 的 `qcm6490-addons.dtsi` 删了 venus `iommus` 适配 downstream 驱动 → mainline `qcom-venus` 硬件编解码在 BSP 上是死路（`dma_set_mask -EIO`；补 iommus 即 SoC 复位）。改用 Armbian 同款 **`radxa/kernel@linux-6.18.2`**（mainline，同仓库换分支，grub-with-dtb 启动模型不变）。

**切换要点**（`qcs6490/config.jsonnet`）：mainline 只有通用 `defconfig`（无 qcom_defconfig）；`kernel.config` 强制 builtin UFS/QMP-PHY（root-on-UFS 无 initramfs 必需）及 **`FW_LOADER_COMPRESS`/`_ZSTD`**（`/lib/firmware` 全 `.zst`）；**R8169 不可裁**（板载 RTL8168）。构建侧通过 append `.config` + olddefconfig 应用同一 canonical symbol map。

| 子系统（mainline 6.18.2 实板 2026-05-30）| 状态 |
|---|---|
| 启动链 → Kernel 6.18.2 + UFS（**无复位**）| ✓ |
| **硬件视频解码 venus** | ✓ `/dev/video1` 解 H.264/HEVC/MPEG2/VP9（gst `v4l2h264dec` → NV12 1280×720 实跑 ~328fps）|
| **硬件视频编码** | ✓（**需 EL2**）：venus `/dev/video1` 出 H.264/HEVC。**前提＝UEFI `Hypervisor Override` 开启、系统以 EL2 启动**（`/dev/kvm` 在、`/dev/mtd0` 失）；EL1 下喂帧即整机复位（2026-09-28 起 flange 用 KVM 组合 DTB，UEFI 保持出厂 `Auto` 即进 EL2）。EL2 实测 `v4l2h264enc` 720p NV12→6.46MB 有效 H264（NAL 1/5/7/8、Baseline）、零复位。真根因是 EL1↔EL2（hypervisor 介导编码器 CP/secure 内存），**与驱动/固件/发行版无关**——此前"死路"证据矩阵（2 内核×2 驱动×2 发行版×2 工具）全是 EL1。详见记忆 `qcs6490-venus-encode-soc-reset` |
| GPU Adreno 643（`/dev/dri/card0`+`renderD128`，a660 fw）| ✓ |
| 有线网 enp1s0（r8169 + REALTEK_PHY）| ✓ |
| GENI i2c（qupv3fw.elf.zst 加载）| ✓ |
| **AIC8800 wifi** | ✓ OOT 模块 `aic8800_fdrv`+`aic_load_fw`，iface `wlx<MAC>` 扫到 23 AP |
| **adb-gadget** | ✓ `usb_1` 改 peripheral → UDC `a600000.usb` configured，Mac `adb devices` 可见 |
| **魅族 E3 屏**（meizu-e3-bringup product）| ✓ 实板**有画面 + 可触摸 + 背光可控**（2026-05-30）；mainline 适配见下节坑 #6/#11 |
| 音频 | ⏳ 待在 mainline 重验（LPASS soundwire codec）|

**AIC8800 wifi + adb（2026-05-30 实板）**：mainline 不带 in-tree aic8800 → 以 OOT 模块从 `radxa-pkg/aic8800` 编（`oot_sources`+`oot_modules`，见 `qcs6490/config.jsonnet`）。三处治理：① `get_tx_power` cfg80211 6.18 新增 `radio_idx`/`link_id` 参数（`patches/aic8800/0001`）；② 顶层 Makefile 强制 `-j$(nproc)` + 父 jobserver 继承 → 大 cc1 并发 OOM，配方改 **`MAKEFLAGS= make -j1`** 真串行；③ sed `{}` 要 `{{}}` 转义避开 `str.format`。固件 `/lib/firmware/aic8800D80/` 与驱动 `aic_default_fw_path` 吻合。adb 真根因：mainline 两个 USB 控制器都 `dr_mode=host` → 无 UDC；`patches/kernel/0002` 把 `usb_1`(usb@a600000, USB-A SS 口) 改 peripheral（HDMI 走 qmpphy lane0/1 独立、不受影响；usb_2 hub+wifi 保持 host）+ gadget 栈 builtin。配合 0001 dwc3 stall patch + usbdevice 自愈，开机自动上线（NRestarts=1）。

## bring-up 完成清单（2026-05-29 实板更新）

| 子系统 | 状态 | 备注 |
|---|---|---|
| 启动链 XBL→EDK2→GRUB→Kernel 6.6.90 | ✓ | console=ttyMSM0,115200 |
| systemd is-system-running | ✓ running | 无 failed unit |
| hostname / sudo 解析 | ✓ | 基类 `_install_hostname` 写 `/etc/hostname` + `/etc/hosts 127.0.1.1 <board>` |
| Ethernet enp1s0 (r8169) | ✓ DHCP |
| rootfs 首启扩容 → 119 G | ✓ | grow 脚本走 sysfs 兜底 |
| ADB（Mac host） | ✓ | dwc3 clear-stall patch（platform 层） |
| WiFi AIC8800 + regdb + scan | ✓ | iface `wlx<MAC>`，2.4G+5G |
| GPU Adreno 643 — freedreno OpenGL 4.6 / GLES 3.2 / Vulkan turnip 1.3.318 | ✓ | a660_zap + a660_sqe 加载 |
| ADSP PIL (radxa/dragon-q6a/adsp.mbn) | ✓ running | qcom_mdt_loader 自动识别单文件 ELF |
| CDSP PIL + /dev/fastrpc-cdsp | ✓ running | Hexagon NN 接口可用 |
| IPA / MPSS modem | ✓ disabled | 板无 modem 硬件 |
| 魅族 E3 屏（meizu-e3-bringup product，2026-05-29 实板） | ✓ 显示+背光+触摸 probe | 见下方专门章节；触摸坐标 X/Y 标定 follow-up |

## product / variant

`products: [default, meizu-e3-bringup]`，`variants: [debug, release]`（继承平台）。

```
lunch radxa-dragon-q6a-default-debug            # 裸机：含 mesa-utils / vulkan-tools 调试工具
lunch radxa-dragon-q6a-default-release          # 裸机精简
lunch radxa-dragon-q6a-meizu-e3-bringup-debug   # + 魅族 E3 MIPI-DSI 屏（显示+触摸+背光）
```

`default` 产物与本变更前 byte-identical（fdtoverlay 分支不触发）；`meizu-e3-bringup` 经条件键注入 [[meizu-e3-panel]] 包，drivers 选 `sec_ts`/`sgm37604a`/`panel_meizu_e3` 三个 OOT 驱动。

## 关键板级配置

- `rootfs.extra_firmware`：
  - `radxa-aic8800` → `/lib/firmware/aic8800D80/`（QCLINUX BSP driver 写死路径，与 a7a 路径不同）
  - `radxa-firmware-qcs6490` → `/lib/firmware/qcom/qcs6490/radxa/dragon-q6a/{adsp,cdsp}.mbn + jsn`（从 `radxa-pkg/radxa-firmware` 0.2.31 取）

## 板级 patch

`patches/kernel/0001-dts-radxa-dragon-q6a-PIL-firmware-paths.patch`：
- `&remoteproc_adsp / &remoteproc_cdsp` 把 firmware-name 从 `qcom/qcs6490/{adsp,cdsp}.mdt` 改成 `qcom/qcs6490/radxa/dragon-q6a/{adsp,cdsp}.mbn`，对齐 Radxa firmware deb 的实际路径（单文件 .mbn，qcom_mdt_bins_are_split 自动识别）
- `&remoteproc_mpss { status = "disabled"; }` — 无 modem；同时止住 mpss reserved-mem 冲突触发的 ioremap_prot WARNING
- `&ipa { status = "disabled"; }` — Q6A 无 modem 通路用不到 IPA

## 魅族 E3 屏（meizu-e3-bringup product，2026-05-29 实板）

跨 SoC 复用 [[meizu-e3-panel]] 硬件特性包：第三块板（rock5b=RK3588 → a7a=A733 → 本板=QCS6490）。Q6A 上 `drivers/gpu/drm/panel/` 是纯 mainline 风格、无通用 DSI panel driver（QCLINUX BSP 6.6.90 共 91 个驱动一型一驱），故由包内新增 OOT `panel_meizu_e3` 驱屏（`compatible = "meizu,e3-panel"`，~250 行 drm_panel 风格）。overlay = `qcom-qcs6490-radxa-dragon-q6a-meizu-e3-panel.dtso`，骨架抄同 LCD FPC 连接器的 `qcs6490-radxa-dragon-q6a-radxa-display-8hd.dtso`。

**bring-up 通过项**：

| 子系统 | 状态 | 证据 |
|---|---|---|
| 显示 DSI-1 connector | ✓ connected @ 1080×2160 | `/sys/class/drm/card0-DSI-1/status` + `modes` |
| `panel_meizu_e3` attach msm_dsi | ✓ | drm card0 + renderD128 + `/dev/dri/card0` |
| 背光 SGM37604A I2C | ✓ brightness 2048/4095 | `/sys/class/backlight/sgm37604a/{,actual_,max_}brightness` |
| 触摸 sec_ts probe | ✓ device_id AC 6F 70 | input `Samsung Electronics Touchscreen 1223` on event2；IRQ 201 (msmgpio 81) 实测累计中断（手摸时涨）；坐标 X/Y 翻转/镜像方向标定留 follow-up |
| 三 OOT 模块加载 | ✓ loaded（kernel taint `E`） | `lsmod` 含 panel_meizu_e3 + sec_ts + sgm37604a |
| i2c-13 bus | ✓ Firmware load Success | dmesg `Firmware load for I2C protocol is Success for xfer mode 1`；13-0036 + 13-0048 client |

LCD FPC（J10，原理图 v1.21 sheet 31）引脚：

| 信号 | Q6A SoC net |
|---|---|
| DSI 数据 | DSI0 4-lane（mdss_dsi0_out） |
| 屏复位 LCD-RST | `&tlmm 44`（active-low） |
| 触摸+背光 I2C | `&i2c13`（QUP1_SE5 / qupv3_id_1，100 kHz） |
| 触摸 IRQ / RST | `&tlmm 81` / `&tlmm 105` |
| 主供电 3V3 | `vcc_3v3_lcd`（SGM2578AAD load-switch，`&tlmm 80` 控） |
| IO 1V8 | `&vreg_l1c_1p8`（PMIC PM7325 LDO L1C 直出，always-on） |

**两条背光通道电气并联但功能互斥** ⚠️：原理图把 (a) 板载 SY7203 boost LED 驱动（VCC_LEDA/LEDK → FPC pin 35/39，由 PM7350C GPIO_08 的 EDP_BLPWM 控制）与 (b) FPC pin 26/27 = i2c13 → 屏自带 SGM37604A I2C 背光芯片，**两条都布到 FPC**。E3 屏 LED 串接 SGM37604A 内部、FPC LED+/- 悬空，本变更选 (b)：不引用 `&pm8350c_pwm` / `&pm8350c_gpios`、不声明 `pwm-backlight`；SY7203 EN 默认悬置 → boost 不工作 → LED+/- 安全。

触摸 TP-RST 走 `regulator-fixed`（always-on/boot-on）拉高解复位，与 a7a 对称；不用 gpio-hog（虽然 mainline tlmm 支持，但保持两 SoC 行为一致便于维护）。

**构建期 fdtoverlay 合并** ⚠️：Q6A 启动链 GRUB(grub-with-dtb) 不支持运行时 DT overlay，包内 `.dtbo` 经 [[构建期 dtb overlay 合并]] 在 `builder/platforms/qualcommqcs6490/rootfs.py::_install_kernel_boot` 由 `fdtoverlay` 工具与 base dtb 合并，覆盖式写 rootfs `/boot/qcs6490-radxa-dragon-q6a.dtb`。GRUB `grub.cfg` 一行不变。

### Q6A 适配特有的 9 个坑（按命中顺序）

1. **kernel.py 漏调 OOT pipeline**（旧帐）：`add-qcs6490-radxa-dragon-q6a` 当时无 OOT 故 `Qcs6490KernelBuilder.compile` 跳过 `_compile_oot_modules` / `_install_oot_modules`；本次引入 3 个 OOT 暴露。修：照 a733 加两行调度。
2. **base dtb 无 `__symbols__`**：QCLINUX BSP `scripts/Makefile.lib:372` 仅对 `base-dtb-y` 加 `-@`；`dtb-y` 默认不带。修：kernel.py 传 `DTC_FLAGS_<dtb>=-@` 经 per-target hook 启用。
3. **dtso 错抄 mainline radxa branch label**：`&vcc_3v3` / `&vcc_1v8` 在 QCLINUX BSP base 不声明 → fdtoverlay `FDT_ERR_NOTFOUND`。修：dtso 删 `vin-supply`、`vccio-supply` 改 `&vreg_l1c_1p8`（PMIC 直出）。
4. **`MODULE_SIG_FORCE=y` 拒绝未签名 OOT**：通过 `kernel.config.CONFIG_MODULE_SIG_FORCE = "n"` 关闭。Follow-up 正向方案是 `_install_oot_modules` 接 `sign-file` + 内核 `certs/signing_key.pem`，跨平台单独立项。
5. **sec_ts / sgm37604a ABI 漂移**：`class_create` 6.4 去首参、`i2c_driver.probe` 6.6 删 id 参数、pinctrl/consumer.h 不再间接 include；**mainline 6.18 续增**：`<asm/fb.h>` 6.11 arm64 移除（驱动本不用其符号，删）、`<asm/unaligned.h>` 6.12 迁 `<linux/unaligned.h>`（`__has_include` 分流）、`GPIOF_DIR_IN` 删 → 用 `GPIOF_IN`、`FB_EVENT_BLANK` 6.18 fb.h 移除（fb_notifier 是死代码，按历史值 0x09 `#ifndef` 兜底）。修：`LINUX_VERSION_CODE`/`__has_include`/`#ifndef` 守卫，三板（rock5b/a7a/q6a）通用。
6. **i2c-geni firmware 加载（BSP↔mainline 反转）**：QCLINUX BSP `geni_load_se_firmware` 缺 DT 属性 `return -EINVAL` 故 dtso 曾加 `qcom,load-firmware;`；**mainline `i2c-qcom-geni` 不读该属性**，`geni_se_read_proto()` 返回 `INVALID_PROTO` 时**自动** load，故 mainline overlay 已删 `qcom,load-firmware`。
7. **QUP firmware 路径错位**：`request_firmware("qupv3fw.elf")` 找顶层；linux-firmware 装在 `/lib/firmware/qcom/qcs6490/qupv3fw.elf.zst`。修：平台 overlay symlink `qupv3fw.elf.zst -> qcom/qcs6490/qupv3fw.elf.zst`（`FW_LOADER_COMPRESS_ZSTD=y` 自动解压）。
8. **usrmerge 冲突**：overlay 顶层 `lib/` 撞 rootfs `/lib -> /usr/lib` symlink，`cp -a` 报 `cannot overwrite non-directory ... with directory`。修：所有平台 overlay 走 `usr/lib/...` 路径而非 `lib/...`。
9. **sec_ts DT prop 私有命名**：sec_ts 不读 `interrupts-extended`，用 `sec,irq_gpio` + `gpio_to_irq()`。修：dtso 加 `sec,irq_gpio = <&tlmm 81 0>` + `sec,skip-fw-update-on-probe`（a7a 同款 workaround）。
10. **sec_ts probe 时 vcc_3v3_lcd 未上电（首次 probe -ENXIO）**（2026-05-29 后补）：触摸 IC 实际供电链路 = `vcc_3v3_lcd` rail → FPC pin 2 → panel 模组内 sec_ts IC，但 sec_ts 驱动是 OEM 老代码不调 `regulator_get/enable`、节点本身没 `vdd-supply`（驱动不消费）。`vcc_3v3_lcd` 名义上由 `panel@0` 引用，而 `panel_meizu_e3` 只在 `.prepare()`（DRM modeset 时）才 enable vdd，时机远晚于 sec_ts probe (6.86 s) → 触摸 IC 无电、i2c 0x48 -ENXIO、probe 退出 -ENOMEM。次生：`sec_ts_parse_dt` 错误路径无 `gpio_free`，首次失败后 gpio 81 残留，unbind/bind 与 rmmod/modprobe 二次重试均报 `Unable to request tsp_int`。修（双管齐下）：dtso `vcc_3v3_lcd` 加 `regulator-always-on; regulator-boot-on;`（regulator core 起来即 tlmm 80 拉高，rail 在 sec_ts probe 前已稳定上电；panel `enable/disable` ref-count 仍正常工作，仅 unprepare 时不真关电，bringup 阶段可接受）+ `sec_ts_main.c` 在 `parse_dt` / `setup_drv_data` / `probe::err_get_drv_data` 三处错误路径补 `gpio_free`（健壮性）。a7a 无此问题：a7a 的 panel `power0/1-supply` 走 Allwinner BSP 系统级 rail（`reg_dc1sw1`/`reg_bldo2`，近似 always-on），sec_ts probe 时已有电。Follow-up：让 `touchscreen@48` 显式声明 `vdd-supply = <&vcc_3v3_lcd>` 并改 sec_ts 驱动主动 `regulator_get/enable` 后即可去掉 always-on（power policy 阶段处理）。
11. **i2c13 `qcom,enable-gsi-dma` 致触摸/背光全失败（mainline 6.18.2，2026-05-30）**：mainline base board dts 给 i2c13（"External touchscreen" bus）声明了 `qcom,enable-gsi-dma`，GSI/GPI DMA 模式对 sec_ts(0x48)/sgm37604a(0x36) 的小事务**全部 `GPI transfer failed: -5`** → sec_ts 读 device id 全 0（应 AC,6F,70）、背光写失败。default 产物 i2c13 无从机不触发传输故不暴露。`fdtoverlay` 不支持 `/delete-property/`（libfdt overlay apply 纯加性、无删除编码），且布尔属性没法用赋值中和，故只能 patch base dts：`patches/kernel/0003` 删该行 → geni i2c 回退 FIFO 模式，触摸/背光恢复（对 default 无害）。

    > **⚠️ 7.0.2 更正（2026-06-01，已实机验证）**："删 `qcom,enable-gsi-dma` 即回退 FIFO"在 **mainline 7.0.2 不再成立**。7.0.2 的 `i2c-qcom-geni` probe 仅当 `proto==GENI_SE_INVALID_PROTO`（SE 未初始化）才调 `geni_load_se_firmware()`，而该 flag 的**唯一读取点**就在此函数内（i2c 驱动本身不读它，只读硬件 `GENI_IF_DISABLE_RO & FIFO_IF_DISABLE`）。bootloader（对齐 radxa rsdk）现把 SE5 预 provision 成 I2C-GSI（`proto==I2C`、`FIFO_IF_DISABLE` 置位），probe 跳过重载 → `0003` 删的 flag 永不被读、SE 仍 GSI（活动 DT 已确认 flag ABSENT 但仍 GSI）。对照 `i2c10`(RTC, SE3, 声明 gsi-dma) 的 GSI 正常 → 是 SE5 的 GSI provision 坏。**修复 = `patches/kernel/0006-i2c-geni-force-fifo-on-gsi-mismatch.patch`**：probe 里当 DT 无该 flag 但 SE 起来是 GSI 时强制重调 `geni_load_se_firmware(GENI_SE_I2C)` 回 FIFO（`0003` 保留，删 flag 是 0006 触发条件之一）。实机：device id `0,0,0`→`AC,6F,70`、`GPI transfer failed` 48→0、触摸 IRQ 0→430+evtest 识别、背光亮、`i2c10` 不回归、零 oops。**验证坑**：`i2c_qcom_geni` 不能 `rmmod` 热插（扯崩 i2c-13 背光→panel→DRM、内核 Oops），须替换 `/lib/modules/<ver>/.../i2c-qcom-geni.ko.zst`（`MODULE_SIG` 未开免签名）+ 重启；补丁在**模块**里不在 vmlinuz。详见记忆 `qcs6490-touch-i2c13-gsi-fifo`、change `fix-qcs6490-touch-i2c13-fifo`。

    > **⚠️ 再更正（2026-09-27）**：上文"`i2c10` 的 GSI 正常"只在 EL1 下成立。`260120` 固件 + EL2 时，`i2c10` 申请 GPI 通道即同步外部中止、系统无法启动。现由 `0007` 删除 `i2c10` 的 flag，`i2c10` 同样经 `0006` 走 FIFO。见上文"EL2 启动与 GPI DMA"与 change `fix-qcs6490-i2c10-fifo-el2`。

## 易踩坑

- **fstab 别挂 /boot/efi**：4K LBA UFS 上 512-sector FAT vfat 报 superblock 无效；rootfs.py 已只写 rootfs 行。
- **AIC8800 固件路径与 a7a 不同**：a7a 用源码补丁改 `CONFIG_AIC_FW_PATH = /lib/firmware/aic8800_fw/USB`；Q6A QCLINUX BSP 把路径写死 `/lib/firmware/aic8800D80/`，board config 直接装到对位路径。
- **WiFi 接口名 `wlx<MAC>`**：systemd predictable naming + USB 总线前缀；要 `wlan0` 加 kernel cmdline `net.ifnames=0`。
- **ADSP qrtr/fastrpc-adsp -12 ENOMEM（2026-05 bring-up 时的记录，已过时）**：当时 ADSP PIL 已 running，但 `/dev/fastrpc-adsp` 没出现（CDSP 正常）。mainline 7.0.2 + EL2 实测（2026-09-27）`/dev/fastrpc-adsp` 存在且 FastRPC 调用成功，见上文"EL2 下 ADSP / CDSP"。
- **mpss reserved 246 MiB @ 0x8b800000 与其他段冲突**：DT 已 disable，但 boot 早期 reserved-mem 报警告无法消除（不影响功能）。

## 未启用项

- PCIe NVMe / USB3 host 模式 / HDMI / DSI camera
- ADSP 音频通路（pcm5102a / sof-audio）
- Bluetooth（AIC8800 BT，需 hcittach + qca firmware）
- Modem（板无硬件）

## 刷写

平台 `QualcommFlashStrategy`，整盘 `edl-ng --memory UFS write-sector 0 raw.img`（`flange flash`）。**SPI 固件单刷 `flange flash --spi-firmware`（Radxa 预编 `flat_build_wp_260120.zip` / 00549-KODIAKWP）——迁到 7.0.2/kodiak DTB 必须配套刷新，旧 `251013` 固件会致 UFS probe 整机复位**；注意 `flange flash` 默认只刷 UFS、不碰 SPI。

### 全新 UFS 初始化

板级 `bootloader.ufs_firehose` 与 `ufs_provisions` 提供两套一次性初始化配置：

```bash
flange flash --provision-ufs lun0-only  # 单用户 LUN，默认 profile
flange flash --provision-ufs qcom       # Qualcomm 官方 LUN 0–7 布局
```

该操作会重建 UFS LUN 布局并清除原数据。初始化完成后设备需要重新进入 EDL，再执行 `flange flash` 写入系统 UFS 镜像。`--spi-firmware` 更新的是独立 SPI NOR 中的 EDK2/XBL 固件，不替代 UFS 初始化，也不会由普通 `flange flash` 自动执行。
