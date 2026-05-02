# Cubie A7Z 外接 ST7789V2 SPI LCD — 实测记录

## 概述

在 Radxa Cubie A7Z (Allwinner A733, 内核 5.15.147+) 上外接 ST7789V2 240×280 SPI LCD 的实测过程与当前状态。

**当前状态：屏幕背光亮，但无像素内容。已定位根因为 pinctrl 驱动 bug。**

## 接线表

| ST7789V2 Pin | 信号 | 40-Pin Header | SoC Ball | pinmux 功能 |
|---|---|---|---|---|
| GND | 地 | PIN_6 (或任一 GND) | — | — |
| VCC | 电源 3.3V | PIN_1 | — | — |
| SCL | SPI Clock | PIN_7 | PB0 | SPI2_SCLK (func 4) |
| SDA | SPI MOSI | PIN_11 | PB1 | SPI2_MOSI (func 4) |
| CS | Chip Select | PIN_31 | PB3 | SPI2_CS0 (func 4) |
| DC | Data/Command | PIN_12 | PB5 | GPIO (func 1) |
| RES | Reset | PIN_35 | PB6 | GPIO (func 1) |
| BLK | 背光 | PIN_2 (5V) 或 PIN_1 (3.3V) | — | 常亮 |

40-pin header 关键脚位：

```
PIN_1 (3.3V)   PIN_2 (5V)       ← VCC / BLK
PIN_7 (SCL)    PIN_8
PIN_11 (SDA)   PIN_12 (DC)
PIN_29 (MISO)  PIN_30 (GND)
PIN_31 (CS)    PIN_32
PIN_35 (RES)   PIN_36
```

## 已完成的软件配置

### 1. Device Tree Overlay

使用 `fdtoverlay` 将 overlay 叠加到 `/boot/extlinux/sunxi.dtb`：

**Overlay 源文件** (`sun60iw2p1-spi2-st7789v2-lcd.dtso`)：

```dts
/dts-v1/;
/plugin/;

/ {
	compatible = "allwinner,sun60i-a733";

	fragment@0 {
		target = <&pio>;

		__overlay__ {
			spi2_pins_default: spi2-pins-default {
				pins = "PB0", "PB1", "PB2";
				function = "spi2";
				drive-strength = <10>;
			};

			spi2_pins_cs: spi2-pins-cs {
				pins = "PB3";
				function = "spi2";
				drive-strength = <10>;
				bias-pull-up;
			};

			spi2_pins_sleep: spi2-pins-sleep {
				pins = "PB0", "PB1", "PB2", "PB3";
				function = "gpio_in";
				drive-strength = <10>;
			};
		};
	};

	fragment@1 {
		target = <&spi2>;

		__overlay__ {
			status = "okay";
			sunxi,spi-bus-mode = <1>;  /* SUNXI_SPI_BUS_MASTER */
			sunxi,spi-cs-mode = <1>;   /* SUNXI_SPI_CS_SOFT */
			pinctrl-0 = <&spi2_pins_default &spi2_pins_cs>;
			pinctrl-1 = <&spi2_pins_sleep>;
			pinctrl-names = "default", "sleep";

			st7789v@0 {
				compatible = "sitronix,st7789v";
				reg = <0>;
				spi-max-frequency = <40000000>;
				spi-rx-bus-width = <1>;
				spi-tx-bus-width = <1>;
				rotate = <90>;
				fps = <60>;
				buswidth = <8>;
				regwidth = <8>;
				width = <240>;
				height = <280>;
				dc-gpios = <&pio 1 5 0>;     /* PB5, ACTIVE_HIGH */
				reset-gpios = <&pio 1 6 1>;  /* PB6, ACTIVE_LOW */
				status = "okay";
			};
		};
	};
};
```

**编译与叠加**（宿主机执行）：

```bash
dtc -@ -I dts -O dtb sun60iw2p1-spi2-st7789v2-lcd.dtso -o sun60iw2p1-spi2-st7789v2-lcd.dtbo
cp /tmp/sunxi.dtb /tmp/sunxi_v2.dtb
fdtoverlay -o /tmp/sunxi_v2.dtb -i /tmp/sunxi_v2.dtb sun60iw2p1-spi2-st7789v2-lcd.dtbo
adb push /tmp/sunxi_v2.dtb /boot/extlinux/sunxi.dtb
```

### 2. 内核模块自动加载

已写入 `/etc/modules-load.d/modules.conf`：

```
fbtft
fb_st7789v
```

### 3. 驱动验证结果

启动后驱动加载成功：

```
fb_st7789v spi2.0: fbtft_property_value: width = 240
fb_st7789v spi2.0: fbtft_property_value: height = 280
fb_st7789v spi2.0: fbtft_property_value: rotate = 90
fb_st7789v spi2.0: fbtft_property_value: fps = 60
graphics fb0: fb_st7789v frame buffer, 280x240, 131 KiB video memory, fps=62, spi2.0 at 40 MHz
```

- SPI2 控制器：**已启用，Master 模式** (GC_REG bit1=1)
- fbtft 驱动：**已绑定 spi2.0**
- DC 引脚 (PB5)：**GPIO out hi** (fbtft 已请求)
- RES 引脚 (PB6)：**GPIO out hi ACTIVE_LOW** (fbtft 已请求)
- SPI 传输统计：**有数据传输**，每帧约 139KB（符合 280×240×2 bytes）
- framebuffer：`/dev/fb0` 可读写，数据写入后 SPI bytes_tx 增长

## 根因：pinctrl 驱动未写入硬件 pinmux 寄存器

### 现象

内核 debugfs 显示 pinctrl 映射正确：

```
pin 32 (PB0): device 2542000.spi function spi2 group PB0
pin 33 (PB1): device 2542000.spi function spi2 group PB1
pin 34 (PB2): device 2542000.spi function spi2 group PB2
pin 35 (PB3): device 2542000.spi function spi2 group PB3
```

但**物理寄存器值**（通过 `/dev/mem` 直接读取 PIO_BASE + PB_bank_offset）：

```
PB_CFG0 = 0x00000500
  PB0: func 0x0 (gpio_in)    ← 应为 0x4 (spi2)
  PB1: func 0x0 (gpio_in)    ← 应为 0x4 (spi2)
  PB2: func 0x5 (hdmi)       ← 应为 0x4 (spi2)
  PB3: func 0x0 (gpio_in)    ← 应为 0x4 (spi2)
```

**结论：pinctrl 框架声称已将 PB0-PB3 设为 spi2，但硬件寄存器未被写入。SPI2 的 CLK/MOSI/CS 信号没有输出到物理引脚。**

### 原因分析

A733 BSP pinctrl 驱动 (`pinctrl-sun60iw2.c`) 有两组 pin table，通过条件编译选择：

```c
#if IS_ENABLED(CONFIG_AW_FPGA_S4) || IS_ENABLED(CONFIG_AW_FPGA_V7)
    // 第一组：PB0 func4=twi0, PB0/PB1 无 spi2
#else
    // 第二组：PB0 func4=spi2, PB1 func4=spi2
#endif
```

当前内核编译时**未启用 CONFIG_AW_FPGA_S4/V7**，应走 `#else` 分支（PB0 func4=spi2）。但实际硬件行为表明，pinctrl 驱动在运行时可能使用了错误的 pin table 或 mux 值映射，导致 `function = "spi2"` 的 mux 值没有正确写入寄存器。

另一种可能：pinctrl 框架的 `pinmux-pins` 显示只是逻辑映射，底层 sunxi pinctrl 驱动在 `set_mux` 回调中可能因 bank 计算或偏移错误而写入了错误地址。

### 手动修复验证

通过 `/dev/mem` 直接写 PIO 寄存器，将 PB0-PB3 设为 func4：

```python
# PB bank offset = 1 * 0x24 = 0x24
# PB_CFG0 offset = PB_bank_base + 0x00
new_cfg0 = (4 << 0) | (4 << 4) | (4 << 8) | (4 << 12)  # PB0-PB3 = func4
            | (1 << 16) | (1 << 20) | (1 << 24)          # PB4-PB6 = gpio_out
write32(0x24, new_cfg0)
```

写入后寄存器确认 `PB_CFG0 = 0x01114444`，PB0-PB3 = func4。但屏幕仍未显示内容——**需要进一步排查**（可能需要同时重置 fbtft 驱动让其重新初始化屏幕，或接线仍有问题）。

## 待排查项

1. **pinctrl 驱动 bug**：确认 pinctrl-sun60iw2.c 的 `set_mux` 回调是否正确计算了 PB bank 的寄存器偏移，是否写入了正确值
2. **手动写寄存器后仍不显示**：可能需要在 pinmux 切换后重新执行 fbtft 的 `init_display`（reset + 初始化命令序列），当前驱动在 probe 时已经发过 init，但那时 pinmux 还没生效
3. **接线确认**：确认 SCL/SDA/CS/DC/RES 各线是否正确对应到 PIN_7/PIN_11/PIN_31/PIN_12/PIN_35
4. **SPI 模式**：ST7789V2 要求 SPI Mode 0 (CPOL=0, CPHA=0)，需确认 TCR 寄存器中 CPOL/CPHA 值
5. **背光确认**：BLK 接了 5V 还是 3.3V？背光是白色/灰色亮光还是纯黑？纯黑可能说明背光没开

## 下一步计划

1. 在设备上接线确认后，执行完整测试：
   - 手动写 pinmux 寄存器 (PB0-PB3 = func4)
   - 卸载再重新加载 fbtft 驱动（让 init_display 在正确 pinmux 下重新执行）
   - 写全屏颜色测试
2. 排查 pinctrl 驱动 `set_mux` 的具体实现，定位为什么寄存器没被写入
3. 根据根因修复 pinctrl 驱动或用启动脚本 workaround

## 关键文件路径

| 文件 | 说明 |
|---|---|
| `/boot/extlinux/sunxi.dtb` | 当前设备上的 DTB（已叠加 overlay） |
| `bsp/drivers/pinctrl/pinctrl-sun60iw2.c` | A733 pinctrl 驱动（有 bug） |
| `bsp/drivers/spi-ng/spi-sunxi.c` | Allwinner SPI 控制器驱动 |
| `src/drivers/staging/fbtft/fb_st7789v.c` | fbtft ST7789V 驱动 |
| `bsp/include/dt-bindings/spi/sunxi-spi.h` | SPI 常量定义 |
