# Cubie A7Z 外接 ST7789V2 SPI LCD 方案

## 概述

为 Radxa Cubie A7Z (Allwinner A733) 外接一块 ST7789V2 240×280 SPI LCD 屏幕，通过 SPI2 控制器驱动。

## 硬件信息

| 项目 | 值 |
|---|---|
| 设备 | Radxa Cubie A7Z |
| SoC | Allwinner A733 (sun60iw2p1) |
| 屏幕 | ST7789V2 240×280 SPI LCD |
| 屏幕 Pin | GND, VCC, SCL, SDA, RES, DC, CS, BLK |

## 接线表

| ST7789V2 Pin | 信号 | 40-Pin Header | SoC Ball | pinmux 功能 |
|---|---|---|---|---|
| GND | 地 | PIN_6 (或任一 GND) | — | — |
| VCC | 电源 (3.3V) | PIN_1 | — | — |
| SCL | SPI Clock | PIN_7 | PB0 | SPI2_SCLK (func 4) |
| SDA | SPI MOSI | PIN_11 | PB1 | SPI2_MOSI (func 4) |
| CS | Chip Select | PIN_31 | PB3 | SPI2_CS0 (func 4) |
| DC | Data/Command | PIN_12 | PB5 | GPIO |
| RES | Reset | PIN_35 | PB6 | GPIO |
| BLK | 背光 | PIN_36 | PB4 | GPIO (可选) |

> **背光可选**：BLK 接 PIN_36 (PB4) 可软件控制开关；接 PIN_1 (3.3V) 则常亮。

## 引脚冲突分析

Cubie A7Z 的 SPI2 使用 PB bank 引脚，与以下默认功能冲突：

| SoC 引脚 | 40-Pin | SPI2 用途 | 默认功能 | 板级 DTS 状态 |
|---|---|---|---|---|
| PB0 | PIN_7 | SCLK | uart2 TX | disabled |
| PB1 | PIN_11 | MOSI | uart2 RX | disabled |
| PB2 | PIN_29 | MISO | uart2 CTS/RTS | disabled |
| PB3 | PIN_31 | CS0 | uart2 CTS/RTS | disabled |
| PB4 | PIN_36 | — (BLK GPIO) | i2s0 MCLK | 需检查 |
| PB5 | PIN_12 | DC GPIO | i2s0 BCLK | 需禁用 |
| PB6 | PIN_35 | RES GPIO | i2s0 LRCK | 需禁用 |

- **uart2**：板级 DTS 已 `status = "disabled"`，不影响 SPI2 启用。
- **i2s0**：overlay 中需显式禁用以释放 PB5/PB6（会牺牲板载音频输出）。

## 为什么是 SPI2

Cubie A7Z 共有 SPI0-SPI3 四个控制器，但可用性如下：

| 控制器 | 可用引脚组 | 是否引出到 40-Pin | 结论 |
|---|---|---|---|
| SPI0 | PC bank (PC2/3/4/12) | 否（用于 eMMC） | 不可用 |
| SPI0 | PF bank (PF24/25/29/31) | 否（用于 SD/SDIO） | 不可用 |
| SPI1 | 无 40-Pin 映射 | 否 | 不可用 |
| **SPI2** | **PB bank (PB0-PB6)** | **是** | **唯一可用** |
| SPI3 | 无 40-Pin 映射 | 否 | 不可用 |

## Device Tree Overlay

文件名遵循 radxa-overlays 命名规范：`sun60iw2p1-spi2-st7789v2-lcd.dtso`

```dts
/dts-v1/;
/plugin/;
#include <dt-bindings/spi/sunxi-spi.h>
#include <dt-bindings/gpio/sun4i-gpio.h>
#include <dt-bindings/gpio/gpio.h>

/{
	metadata {
		title = "Enable ST7789V2 240x280 SPI LCD on SPI2";
		compatible = "radxa,cubie-a7z";
		category = "display";
		exclusive = "PB0", "PB1", "PB2", "PB3", "PB5", "PB6";
		description = "Enable ST7789V2 240x280 SPI LCD on SPI2\n"
			"PIN7(CLK), PIN11(MOSI), PIN29(MISO), PIN31(CS0)\n"
			"PIN12(DC), PIN35(RES)";
	};
};

&pio {
	spi2_pins_default: spi2@0 {
		pins = "PB0", "PB1", "PB2";
		function = "spi2";
		drive-strength = <10>;
	};

	spi2_pins_cs: spi2@1 {
		pins = "PB3";
		function = "spi2";
		drive-strength = <10>;
		bias-pull-up;
	};

	spi2_pins_sleep: spi2@2 {
		pins = "PB0", "PB1", "PB2", "PB3";
		function = "gpio_in";
		drive-strength = <10>;
	};
};

&i2s0 {
	status = "disabled";
};

&spi2 {
	clock-frequency = <50000000>;
	pinctrl-0 = <&spi2_pins_default &spi2_pins_cs>;
	pinctrl-1 = <&spi2_pins_sleep>;
	pinctrl-names = "default", "sleep";
	sunxi,spi-bus-mode = <SUNXI_SPI_BUS_MASTER>;
	sunxi,spi-cs-mode = <SUNXI_SPI_CS_SOFT>;
	status = "okay";

	st7789v2@0 {
		compatible = "sitronix,st7789v";
		reg = <0x0>;
		spi-max-frequency = <40000000>;
		spi-rx-bus-width = <1>;
		spi-tx-bus-width = <1>;
		rotate = <90>;
		fps = <60>;
		buswidth = <8>;
		regwidth = <8>;
		width = <240>;
		height = <280>;
		dc-gpios = <&pio PB 5 GPIO_ACTIVE_HIGH>;
		reset-gpios = <&pio PB 6 GPIO_ACTIVE_LOW>;
		status = "okay";
	};
};
```

### Overlay 说明

| 属性 | 值 | 说明 |
|---|---|---|
| `compatible` | `sitronix,st7789v` | ST7789V/V2 在 fbtft 驱动中共用此 compatible |
| `spi-max-frequency` | 40MHz | ST7789V2 最大 SPI 时钟 |
| `rotate` | 90 | 可根据实际显示方向调为 0/90/180/270 |
| `fps` | 60 | 帧率 |
| `dc-gpios` | PB5 (PIN_12) | Data/Command 引脚，高电平为数据 |
| `reset-gpios` | PB6 (PIN_35) | Reset 引脚，低电平有效 |
| `sunxi,spi-cs-mode` | SOFT | 软件管理 CS，与 radxa-overlays 一致 |

### 背光软件控制（可选）

如需软件控制背光，在 `st7789v2@0` 节点中添加：

```dts
		backlight-gpios = <&pio PB 4 GPIO_ACTIVE_HIGH>;
```

并将 exclusive 字段补上 `"PB4"`。

## 加载方式

### 方式一：rsetup（推荐）

将 `.dtso` 编译为 `.dtbo` 后放入 radxa-overlays 包，通过 `rsetup` 菜单启用。

### 方式二：手动 dtoverlay

```bash
# 编译
dtc -@ -I dts -O dtb -o sun60iw2p1-spi2-st7789v2-lcd.dtbo sun60iw2p1-spi2-st7789v2-lcd.dtso

# 复制到 overlays 目录
sudo cp sun60iw2p1-spi2-st7789v2-lcd.dtbo /boot/dtbs/allwinner/overlays/

# 加载（在 /boot/armbianEnv.txt 或 /boot/extlinux/extlinux.conf 中添加）
overlays=sun60iw2p1-spi2-st7789v2-lcd
```

## 参考来源

- [radxa-pkg/radxa-overlays](https://github.com/radxa-pkg/radxa-overlays) — cubie-a5e SPI overlay 格式参考
- Allwinner A733 BSP pinctrl 驱动 — PB bank SPI2 function 4 映射
- Cubie A7Z 板级 DTS — `sun60i-a733-cubie-a7z.dts`
