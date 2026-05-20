---
title: radxa-cubie-a7a
type: board
status: wip
sources:
  - components/board/radxa-cubie-a7a/config.py
  - components/board/radxa-cubie-a7a/overlay/etc/usbdevice.conf
  - components/board/radxa-cubie-a7a/overlay/etc/modules-load.d/aic8800.conf
  - components/board/radxa-cubie-a7a/overlay/etc/modprobe.d/aic8800.conf
related:
  - "[[radxa-cubie-a7z]]"
  - "[[allwinnera733 平台]]"
  - "[[lunch-build-flash 流程]]"
  - "[[新增板级支持]]"
updated: 2026-05-21
---

## TL;DR

Radxa Cubie A7A，Allwinner A733（sun60iw2p1）SoC，A7 家族主线板。AXP318 PMIC、AC101B 板载音频直挂、MIPI DSI + HDMI 主显，AIC8800 D80 USB Wi-Fi。零 platform 改动、零补丁、零板私有 dtso，纯加板。

## product / variant

继承 allwinnera733 平台默认：`products: [default]`，`variants: [debug, release]`。

```
lunch radxa-cubie-a7a-default-debug
lunch radxa-cubie-a7a-default-release
```

## 关键差异点

| 项 | 值 |
|---|---|
| DTB | `sun60i-a733-cubie-a7a` |
| kernel_device.board_dts_path | `configs/cubie_a7a/linux-5.15/board.dts` |
| bootloader target | `radxa-cubie-a7a` |
| PMIC | AXP318（vs a7z 不同型号） |
| 板载音频 | AC101B 直挂 i2c@3e |
| 主显示 | MIPI DSI + HDMI 直出（首版仅 HDMI） |

## vs [[radxa-cubie-a7z]] 差异

- vendor_overlays：复用 a7z 全集减 `cubie-a7z-reroute-audio-from-hdmi-to-typec-dp.dtbo`（a7a AC101B 直挂，不需 HDMI→TypeC-DP 音频 reroute）
- 默认 overlay 仅启 `cubie-a7a-enable-sunxi-ac101-sound-card.dtbo`；a7z 默认启 ST7789V SPI 小屏 + 13m camera
- 无板私有 dtso / panel firmware（a7a 无 ST7789V SPI 小屏）
- 无板级 patch（a7z 也无）
- AIC8800 USB Wi-Fi 链路与 a7z 字节等价（modules-load / modprobe sha256 校验）

## 首版验收范围

- 串口 console（earlyprintk=sunxi-uart + ttyAS0,115200，平台层提供）
- systemd 启动通过、`hostname` = `radxa-cubie-a7a`
- AIC8800 USB Wi-Fi 上线（`ip link` 含 `wlan0`）
- AC101B 板载音频（`aplay -l` 含 `sunxi-ac101b`）
- SSH 登录（`flange/flange`）

## 未启用项

- **MIPI DSI 主屏**：`board.dts` 中 `panel: panel@0` 为 `allwinner,virtual-panel` placeholder，需具体面板 init 序列方可点亮，独立变更承接
- GPU（IMG BXM PowerVR）/ NPU / VPU 硬解
- PoE / camera / display overlay 默认启用（仅作 vendor_overlays 候选）

## AIC8800 USB Wi-Fi

链路与 a7z 完全一致：`wifi.aic8800_usb=True` + `rootfs.+extra_firmware` 两条 entry（扁平 `aic8800_fw/USB/` + 芯片子目录 `aic8800D80/`）。USB driver 自动 enumeration，无 DTS 节点。

## 刷写

平台层默认 `dd` 模式（SD 卡）。U-Boot 三件套（sdcard / ufs / spinor）均产出，UFS / SPI-NOR 启动按需。

## 易踩坑

- vendor overlay 列表与 a7z 显式重复 20 行（决策：[[../openspec/changes/add-a733-radxa-cubie-a7a/design.md]] 决策 2）。上游加新 sun60iw2p1 overlay 时需在两块板各自补一行。
- AXP318 PMIC 若内核驱动未启用，apply 阶段 `dmesg | grep axp` 会报 unbound，需 SoC 层补 fragment（独立变更）。
- a7a board.dts 的 `allwinner,virtual-panel` placeholder 是 BSP 标准，DSI host 启动行为为 nodev，正常情况下不会卡死。
