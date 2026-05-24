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
  - "[[硬件特性包]]"
updated: 2026-05-23
---

## TL;DR

Radxa Cubie A7A，Allwinner A733（sun60iw2p1）SoC，A7 家族主线板。AXP318 PMIC、AC101B 板载音频直挂、MIPI DSI + HDMI 主显，AIC8800 D80 USB Wi-Fi。零 platform 改动、零补丁、零板私有 dtso，纯加板。

## product / variant

`products: [default, meizu-e3-bringup]`，`variants: [debug, release]`（variants 继承平台默认）。

```
lunch radxa-cubie-a7a-default-debug            # 裸机：HDMI 直出 + AC101B 音频
lunch radxa-cubie-a7a-meizu-e3-bringup-debug   # + 魅族 E3 MIPI-DSI 屏（显示+触摸+背光）
```

`default` 产物与加 product 前 byte-identical；`meizu-e3-bringup` 经条件键注入 [[硬件特性包]] `meizu-e3-panel`。

## 关键差异点

| 项 | 值 |
|---|---|
| DTB | `sun60i-a733-cubie-a7a` |
| kernel_device.board_dts_path | `configs/cubie_a7a/linux-5.15/board.dts` |
| bootloader target | `radxa-cubie-a7a` |
| PMIC | AXP318（vs a7z 不同型号） |
| 板载音频 | AC101B 直挂 i2c@3e |
| 主显示 | HDMI 直出（default）；MIPI DSI 魅族 E3 屏（meizu-e3-bringup） |

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

## 魅族 E3 屏（meizu-e3-bringup product）

同屏跨 SoC 复用 [[硬件特性包]]：`sec_ts`/`sgm37604a` 两 OOT 驱动零改动，仅 panel overlay 按 sunxi 显示栈重写（rock5b 是 Rockchip 栈，不可移植）。overlay = `sun60i-a733-cubie-a7a-meizu-e3-panel.dtso`，骨架抄同连接器的 `cubie-a7a-radxa-display-8hd`：`allwinner,panel-dsi` 经 board.dts `allwinner,virtual-panel` 的 OF-graph 中转挂 `&dsi0`。背光走屏自带 SGM37604A I2C 芯片（非 8hd 的 pwm-backlight）。

LCD FPC（J10）引脚（原理图 v1.10，与 8hd 1:1 印证）：

| 信号 | A733 PIO / 总线 |
|---|---|
| DSI 数据 | DSI0 4-lane（PD0–PD9） |
| 屏复位 LCD-RST | `&pio PD 21` |
| 触摸+背光 I2C | twi2（PD16/PD17） |
| 触摸 IRQ / RST | PD18 / PD19（RST 走 gpio-hog 解复位） |
| 背光使能 | `&pio PD 23` |
| 电源 3.3V/1.8V | `reg_dc1sw1` / `reg_bldo2` |

init/exit 序列平移自 rock5b；timing 用 E3 原厂高通权威值 **htot1317 / 171.95MHz / 60Hz** + **非 burst** `MIPI_DSI_MODE_VIDEO`（抄 rock5b 的 157MHz/htot1211 出斜纹、burst 出细条纹）。触摸已实板通过（`evtest` 出坐标，X/Y 翻转待标定）。

## 未启用项

- GPU（IMG BXM PowerVR）/ NPU / VPU 硬解
- PoE / camera / display overlay 默认启用（仅作 vendor_overlays 候选）

## AIC8800 USB Wi-Fi

链路与 a7z 完全一致：`wifi.aic8800_usb=True` + `rootfs.+extra_firmware` 两条 entry（扁平 `aic8800_fw/USB/` + 芯片子目录 `aic8800D80/`）。USB driver 自动 enumeration，无 DTS 节点。

## 刷写

平台层默认 `dd` 模式（SD 卡）。U-Boot 三件套（sdcard / ufs / spinor）均产出，UFS / SPI-NOR 启动按需。

## 易踩坑

- vendor overlay 列表与 a7z 显式重复 20 行（决策：[[../openspec/changes/add-a733-radxa-cubie-a7a/design.md]] 决策 2）。上游加新 sun60iw2p1 overlay 时需在两块板各自补一行。
- AXP318 PMIC 若内核驱动未启用，apply 阶段 `dmesg | grep axp` 会报 unbound，需 SoC 层补 fragment（独立变更）。
- meizu-e3-bringup overlay 的 panel/触摸/背光节点共用 twi2（PD16/PD17）；该总线同时是 8hd display overlay 的触摸总线，二者互斥不可同时启。
- 触摸 `sec_ts@0x48` 的 a7a 专属两改（rock5b 都不需要）：① `&twi2` 必须 `twi_drv_used=<0>`（engine 模式）——drv 模式扛不住 `read_event` 高频读会 bus-error 卡死；② DT 加 `sec,skip-fw-update-on-probe` 跳过开机自动刷固件——其 `SW_RESET`+强刷会把出厂带 FW 的芯片刷死成永久 NACK。idle 时 sec_ts 中断 ~1850/s 空涨是芯片侧 INT 持续拉低的已知非阻塞项（触摸靠轮询，功能正常）。
