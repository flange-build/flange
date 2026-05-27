---
title: radxa-dragon-q6a
type: board
status: wip
sources:
  - components/board/radxa-dragon-q6a/config.py
  - components/board/radxa-dragon-q6a/patches/kernel/0001-dts-radxa-dragon-q6a-PIL-firmware-paths.patch
  - components/platform/qualcommqcs6490/qcs6490/config.py
  - components/platform/qualcommqcs6490/patches/kernel/0001-dwc3-gadget-preserve-pending-requests-on-clear-stall.patch
  - builder/platforms/qualcommqcs6490/
related:
  - "[[qualcommqcs6490 平台]]"
  - "[[radxa-cubie-a7a]]"
  - "[[FlashStrategy 抽象]]"
updated: 2026-05-28
---

## TL;DR

Radxa Dragon Q6A，Qualcomm QCS6490 (SC7280-class) 单板，128 GB Samsung KLUDG4UHGC-B0E1 UFS，板载 RTL8168 PCIe 千兆 + AIC8800 D80 USB Wi-Fi/BT 模组（与 [[radxa-cubie-a7a]] 同款）。flange 首个 Qualcomm 板，验证 UEFI/GRUB + EDL 刷写 + Adreno 643 freedreno 全栈。

## bring-up 完成清单（2026-05-28 实板）

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

## product / variant

`products: [default]`，`variants: [debug, release]`（继承平台）。

```
lunch radxa-dragon-q6a-default-debug    # 含 mesa-utils / vulkan-tools 调试工具
lunch radxa-dragon-q6a-default-release  # 精简
```

## 关键板级配置

- `wifi.aic8800_usb = True` — 走 a7a 同款 USB 模组（pid 8d80/8d81）
- `+extra_firmware`：
  - `radxa-aic8800` → `/lib/firmware/aic8800D80/`（QCLINUX BSP driver 写死路径，与 a7a 路径不同）
  - `radxa-firmware-qcs6490` → `/lib/firmware/qcom/qcs6490/radxa/dragon-q6a/{adsp,cdsp}.mbn + jsn`（从 `radxa-pkg/radxa-firmware` 0.2.31 取）

## 板级 patch

`patches/kernel/0001-dts-radxa-dragon-q6a-PIL-firmware-paths.patch`：
- `&remoteproc_adsp / &remoteproc_cdsp` 把 firmware-name 从 `qcom/qcs6490/{adsp,cdsp}.mdt` 改成 `qcom/qcs6490/radxa/dragon-q6a/{adsp,cdsp}.mbn`，对齐 Radxa firmware deb 的实际路径（单文件 .mbn，qcom_mdt_bins_are_split 自动识别）
- `&remoteproc_mpss { status = "disabled"; }` — 无 modem；同时止住 mpss reserved-mem 冲突触发的 ioremap_prot WARNING
- `&ipa { status = "disabled"; }` — Q6A 无 modem 通路用不到 IPA

## 易踩坑

- **fstab 别挂 /boot/efi**：4K LBA UFS 上 512-sector FAT vfat 报 superblock 无效；rootfs.py 已只写 rootfs 行。
- **AIC8800 固件路径与 a7a 不同**：a7a 用源码补丁改 `CONFIG_AIC_FW_PATH = /lib/firmware/aic8800_fw/USB`；Q6A QCLINUX BSP 把路径写死 `/lib/firmware/aic8800D80/`，board config 直接装到对位路径。
- **WiFi 接口名 `wlx<MAC>`**：systemd predictable naming + USB 总线前缀；要 `wlan0` 加 kernel cmdline `net.ifnames=0`。
- **ADSP qrtr/fastrpc-adsp -12 ENOMEM**：ADSP PIL 已 running，但 `/dev/fastrpc-adsp` 没出现（CDSP 那边正常）；非阻断，后续优化 reserved-mem 布局。
- **mpss reserved 246 MiB @ 0x8b800000 与其他段冲突**：DT 已 disable，但 boot 早期 reserved-mem 报警告无法消除（不影响功能）。

## 未启用项

- PCIe NVMe / USB3 host 模式 / HDMI / DSI camera
- ADSP 音频通路（pcm5102a / sof-audio）
- Bluetooth（AIC8800 BT，需 hcittach + qca firmware）
- Modem（板无硬件）

## 刷写

平台 `QualcommFlashStrategy`，整盘 `edl-ng --memory UFS write-sector 0 raw.img`；SPI 固件单刷 `flange flash --spi-firmware`（消费 Radxa 预编 `flat_build_wp_260120.zip`）。
