# radxa-cubie-a7a

> 阅读前提：先完成[初学指南](../first-steps.md)的环境准备，运行
> `flange target list radxa-cubie-a7a` 确认当前目标，再按该型号硬件说明匹配介质、接口与下载模式。
> 本页是配置摘要与硬件记录；下文验收只覆盖记录的版本、产品和测试项，不代表当前全部组合已实测。
> [返回板卡索引](README.md) · [构建与刷写流程](../development-guide.md)

## 概述

Radxa Cubie A7A，Allwinner A733（sun60iw2p1）SoC，A7 家族主线板。AXP318 PMIC、AC101B 板载音频直挂、MIPI DSI + HDMI 主显，AIC8800 D80 USB Wi-Fi。板级配置组合平台公共内容与显示功能包。

## product / variant

`products: [default, desktop, meizu-e3-bringup]`，`variants: [debug, release]`（variants 继承平台默认）。

```
lunch radxa-cubie-a7a-default-debug            # 裸机：HDMI 直出 + AC101B 音频
lunch radxa-cubie-a7a-meizu-e3-bringup-debug   # + 魅族 E3 MIPI-DSI 屏（显示+触摸+背光）
```

`default` 不启用 E3 面板功能包；`meizu-e3-bringup` 经条件键注入 [硬件特性包](../packages.md) `meizu-e3-panel`。

## 关键差异点

| 项 | 值 |
|---|---|
| DTB | `sun60i-a733-cubie-a7a` |
| kernel_device.board_dts_path | `configs/cubie_a7a/linux-5.15/board.dts` |
| bootloader target | `radxa-cubie-a7a` |
| PMIC | AXP318（vs a7z 不同型号） |
| 板载音频 | AC101B 直挂 i2c@3e |
| 主显示 | HDMI 直出（default）；MIPI DSI 魅族 E3 屏（meizu-e3-bringup） |

## vs [radxa-cubie-a7z](radxa-cubie-a7z.md) 差异

- vendor_overlays：复用 a7z 全集减 `cubie-a7z-reroute-audio-from-hdmi-to-typec-dp.dtbo`（a7a AC101B 直挂，不需 HDMI→TypeC-DP 音频 reroute）
- 默认 overlay 仅启 `cubie-a7a-enable-sunxi-ac101-sound-card.dtbo`；a7z 默认启 ST7789V SPI 小屏 + 13m camera
- 无板私有 dtso / panel firmware（a7a 无 ST7789V SPI 小屏）
- 无板级 patch（a7z 也无）
- AIC8800 USB Wi-Fi 链路与 a7z 字节等价（modules-load / modprobe sha256 校验）

## 已有启动与用户态记录

- 串口 console（earlyprintk=sunxi-uart + ttyAS0,115200，平台层提供）
- systemd 启动通过、`hostname` = `radxa-cubie-a7a`
- AIC8800 USB Wi-Fi 上线（`ip link` 含 `wlan0`）
- AC101B 板载音频（`aplay -l` 含 `sunxi-ac101b`）
- SSH 登录（`flange/flange`）

## 魅族 E3 屏（meizu-e3-bringup product）

同屏跨 SoC 复用 [硬件特性包](../packages.md)：`sec_ts`/`sgm37604a` 两 OOT 驱动零改动，仅 panel overlay 按 sunxi 显示栈重写（rock5b 是 Rockchip 栈，不可移植）。overlay = `sun60i-a733-cubie-a7a-meizu-e3-panel.dtso`，骨架抄同连接器的 `cubie-a7a-radxa-display-8hd`：`allwinner,panel-dsi` 经 board.dts `allwinner,virtual-panel` 的 OF-graph 中转挂 `&dsi0`。背光走屏自带 SGM37604A I2C 芯片（非 8hd 的 pwm-backlight）。

LCD FPC（J10）引脚（原理图 v1.10，与 8hd 1:1 印证）：

| 信号 | A733 PIO / 总线 |
|---|---|
| DSI 数据 | DSI0 4-lane（PD0–PD9） |
| 屏复位 LCD-RST | `&pio PD 21` |
| 触摸+背光 I2C | twi2（PD16/PD17） |
| 触摸 IRQ / RST | PD18 / PD19（RST 走 gpio-hog 解复位） |
| 背光使能 | `&pio PD 23` |
| 电源 3.3V/1.8V | `reg_dc1sw1` / `reg_bldo2` |

init/exit 序列平移自 rock5b；timing 用 E3 原厂高通权威值 **htot1317 / 171.95MHz / 60Hz** + **非 burst** `MIPI_DSI_MODE_VIDEO`（抄 rock5b 的 157MHz/htot1211 出斜纹、burst 出细条纹）。早期曾观察到 evtest 坐标，但后续出现触摸不应答；不能计为稳定可用，见下方故障边界。

## 未启用项

- NPU 与完整 VPU 外设验收；GPU 已由 SoC 层提供驱动，但桌面加速存在[后端限制](../hardware/a733-graphics.md)
- PoE / camera / display overlay 默认启用（仅作 vendor_overlays 候选）

## AIC8800 USB Wi-Fi

链路与 a7z 完全一致：两条 `rootfs.extra_firmware` entry 通过 canonical source 引用复用 AIC8800 checkout（扁平 `aic8800_fw/USB/` + 芯片子目录 `aic8800D80/`）。USB driver 自动 enumeration，无 DTS 节点。

## 刷写

平台层默认 `dd` 模式（SD 卡）。U-Boot 三件套（sdcard / ufs / spinor）均产出，UFS / SPI-NOR 启动按需。

## 易踩坑

- vendor overlay 列表与 a7z 显式重复 20 行。上游加新 sun60iw2p1 overlay 时需在两块板各自补一行。
- AXP318 PMIC 需匹配驱动；若设备未绑定，先检查运行内核配置和设备树，不能从编译通过推断供电管理已可用。
- meizu-e3-bringup overlay 的 panel/触摸/背光节点共用 twi2（PD16/PD17）；该总线同时是 8hd display overlay 的触摸总线，二者互斥不可同时启。
- 触摸 `sec_ts@0x48` 的 a7a 专属两改（rock5b 都不需要）：① `&twi2` 用 `twi_drv_used=<0>`（engine 模式）；② DT 加 `sec,skip-fw-update-on-probe` 跳过开机自动刷固件（`SW_RESET`+强刷会把出厂带 FW 的芯片刷死成永久 NACK）。
- **触摸稳定性未通过**：后续出现 0x48 不应答与 IRQ 风暴，临时限速曾改善总线和背光，但触摸未恢复。供电瞬态仍需测量，见[触摸与供电故障](../hardware/a7a-touch-power.md)。
