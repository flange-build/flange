# Tab5 all-in-one — P0：工程骨架 + GUD 显示 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: 用 superpowers:subagent-driven-development 逐任务实施。步骤用 `- [ ]` 复选框跟踪。硬件在环：subagent 写码 + 容器外 `get_idf && idf.py build` 编译验证；烧录（BOOT 下载模式）与上板观察由人工控制者做。

**Goal:** 新建 `components/packages/tab5-all-in-one/`，让 M5Stack Tab5 经 USB-C 枚举为 `16d0:10a9`，host 侧 mainline `drm/gud` 出 `/dev/dri/cardN`，把 host 送来的 **640×360 RGB565** 帧经 ESP32-P4 的 PPA 做 **2× 放大 + 90° 旋转**填满 720×1280 面板，支持脏矩形与 LZ4。

**Architecture:** ESP-IDF 工程（ESP32-P4，容器外构建）。GUD 控制状态机 / LZ4 / 协议头从 `cardputer-all-in-one` 拷贝复用；板级部分全部自写薄驱动，只依赖 `esp_lcd_ili9881c`（或 `esp_lcd_st7123`）+ `esp_io_expander_pi4ioe5v6408`，**不引入 esp-bsp / LVGL / esp_video**。DPI 帧缓冲由 `esp_lcd_dpi_panel_get_frame_buffer()` 直接取出，PPA 把解压后的帧就地缩放旋转写进去，**不做额外整帧拷贝**。

**Tech Stack:** ESP-IDF v6.0、`espressif/esp_tinyusb` 2.2.1 + `espressif/tinyusb`、`esp_lcd` MIPI-DSI、`esp_driver_ppa`、`esp_ldo_regulator`、`driver/i2c_master`；host 侧 mainline `drm/gud` + `modetest`。

---

## 范围

本计划只做设计 spec 的**阶段 0 + 阶段 1**（工程骨架 + GUD 显示）。
键盘（阶段 2）、触摸（阶段 3）、音频（阶段 4）、UVC（阶段 5）、主机侧全局内核 config（阶段 6）
各自另立计划，本计划完成后再排。

设计依据：`docs/superpowers/specs/2026-08-11-tab5-all-in-one-design.md`

---

## 关键事实（grounding，全部已核实，不要凭记忆改）

### USB

- **USB-C 接的是 P4 的全速 PHY**。原理图 `Tab5_Schematics_PDF.pdf` p.4：
  J8 → R94/R95(0Ω) → FT1 → R111/R112(33Ω) → 网络 `USB_DEVICE_DP/DM` → P4 pin 52/53
  = GPIO24/25 = `USB1P1`（USB 1.1 全速 PHY）。USB-A 才是 `USB2_OTG_D±` 高速 PHY。
- **⚠️ 头号陷阱**：`esp_tinyusb` 2.2.1 的 `TINYUSB_DEFAULT_CONFIG()` 在 ESP32-P4 上展开为
  **`TINYUSB_CONFIG_HIGH_SPEED`**（`tinyusb_default_config.h:54-57`）。照抄 Cardputer 的
  `TINYUSB_DEFAULT_CONFIG()` 会让 TinyUSB 去驱动 USB-A 那条高速 PHY，**USB-C 永远枚举不出来**。
  必须显式写 `TINYUSB_CONFIG_FULL_SPEED(NULL, NULL)`。
- **P4 全速控制器端点预算**（tinyusb `dwc2_esp32.h`，port 0 = OTG_FS）：
  `ep_count = 7`、`ep_in_count = 5`（含 EP0）、`otg_dfifo_depth = 256` words（1 KB）。
  即最多 **4 条可用 IN 端点**。本计划只用 vendor 的 IN/OUT 各一条，余量充足；
  后续阶段的 UAC/HID/UVC 会把 IN 端点用满，届时再按 spec §2 的降级顺序处理。
- TinyUSB 接管全速 PHY 后 USB-Serial/JTAG 失效 ⇒ 烧录必须按 **BOOT(G35)**；
  日志走 **UART0（TX=G37 / RX=G38，引到 M5-Bus）**，是 IDF 默认控制台，无需改配置。

### 显示

- 面板**原生 720×1280 竖屏**（`BSP_LCD_H_RES=720 / V_RES=1280`），"1280×720" 是横用后的视角。
- MIPI-DSI **2 data lane @ 1000 Mbps**；DSI PHY 供电取自**内部 LDO VO3 @ 2500 mV**。
- 面板控制器随批次为 **ILI9881C** 或 **ST7123**，DPI 时序不同：

  | 面板 | dpi_clock_freq_mhz | hbp / hpw / hfp | vbp / vpw / vfp |
  |---|---|---|---|
  | ILI9881C | 60 | 140 / 40 / 40 | 20 / 4 / 20 |
  | ST7123 | 70 | 40 / 2 / 40 | 8 / 2 / 220 |

- 面板与触摸的电源使能在 **PI4IOE5V6408-1（I2C 0x43）**：`LCD_EN = IO_EXPANDER_PIN_NUM_4`、
  `TOUCH_EN = IO_EXPANDER_PIN_NUM_5`（USB_EN/WIFI_EN 在另一片 0x44，本计划用不到）。
  背光 = **GPIO22**。内部 I2C = **SDA G31 / SCL G32**。
- **PPA 的 `rotation_angle` 是逆时针（CCW）**（`hal/ppa_types.h:30`）。
- `BSP_LCD_BIGENDIAN = 0`、`COLOR_SPACE = RGB` ⇒ **Cardputer 里那段 per-pixel `__builtin_bswap16`
  必须删掉**（它是为抵消 ST7789 4-line SPI 的字节序而加的，DSI 链路上会把颜色搞反）。

### IDF 6.0 的 API 差异（本机只装了 v6.0，`alias get_idf`）

- `esp_lcd_dpi_panel_config_t` **没有 `.pixel_format`**（那是 5.x 写法，esp-bsp 的示例代码用的是旧字段）；
  6.0 用 `.in_color_format` / `.out_color_format`，取值 `LCD_COLOR_FMT_RGB565`。
- `esp_lcd_panel_dev_config_t` 在 `esp_lcd_panel_dev.h`（`esp_lcd_panel_vendor.h` 仍作兼容 shim 保留），
  字段为 `rgb_ele_order` / `data_endian` / `bits_per_pixel` / `reset_gpio_num` / `vendor_config` / `flags`。
- `esp_lcd_ili9881c` 1.1.0 只是把我们填好的 `dpi_config` 转发给 `esp_lcd_new_panel_dpi()`，
  **与 IDF 6.0 兼容**（它自带的两个 helper 宏一新一旧，我们不用宏、直接填结构体即可）。
- I2C 用新的 `driver/i2c_master.h`（`i2c_new_master_bus()` → `i2c_master_bus_handle_t`）。
- `Cardputer README 里的 get_idf_551 已失效`，本机只有 `get_idf`（v6.0）。

### 可直接复用的 Cardputer 资产（拷贝，不改逻辑）

| 文件 | 处理 |
|---|---|
| `gud_protocol.h` | 原样拷贝（内核 vendor，Dual MIT/GPL） |
| `lz4.c` / `lz4.h` | 原样拷贝（BSD-2-Clause） |
| `gud_device.c` / `.h` | 拷贝后改三处：尺寸常量、删 byteswap、`display_blit` 语义 |
| `main/tinyusb_config/tusb_config.h` | **本计划不拷** —— 它存在的唯一目的是开 `CFG_TUD_AUDIO`，而 P0 没有音频接口；vendor 类由 `CONFIG_TINYUSB_VENDOR_COUNT=1` 经 esp_tinyusb 自带的 tusb_config.h 生效。留到音频阶段再连同 `main/CMakeLists.txt` 的 21 行注入块一起从 Cardputer 拷来 |
| `main/CMakeLists.txt` 的 tinyusb 配置注入段 | **本计划不拷**，理由同上（只有 lz4.c 那行 `set_source_files_properties` 要拷，它与音频无关） |

---

## 文件结构

```
components/packages/tab5-all-in-one/
├── README.md                         # Task 6 写
└── firmware/
    ├── .gitignore                    # build/ sdkconfig managed_components/ dependencies.lock
    ├── CMakeLists.txt                # project(tab5_aio)
    ├── sdkconfig.defaults
    ├── partitions.csv
    └── main/
        ├── CMakeLists.txt
        ├── idf_component.yml
        ├── app_main.c                # 编排：board_power → display → gud → tinyusb
        ├── usb_descriptors.{c,h}     # 仅 GUD vendor 接口（后续阶段再加 UAC/HID/UVC）
        ├── gud_protocol.h            # 拷贝
        ├── gud_device.{c,h}          # 拷贝 + 四处改动
        ├── lz4.{c,h}                 # 拷贝
        ├── tab5_pins.h               # 板级 GPIO / 尺寸常量
        ├── board_power.{c,h}         # 内部 I2C + PI4IOE5V6408 + 背光
        └── display_dsi.{c,h}         # LDO + DSI + DPI 面板 + PPA 缩放旋转 + display_blit
```

职责边界：`board_power` 只管上电与 I2C 总线；`display_dsi` 只管把一块 640×360 RGB565
搬到面板上；`gud_device` 只管协议与收帧，对屏的认知仅限 `display_blit()`。
**不要**把 PPA 逻辑写进 `gud_device.c`，也不要让 `display_dsi.c` 认识 GUD 协议。

---

## Task 1：工程骨架 + USB-C 全速枚举（不涉及屏）

目标：Tab5 插 USB-C 到 Linux 主机后枚举为 `16d0:10a9`，`drm/gud` 绑定并创建 `/dev/dri/cardN`。
此时屏幕不亮、host 送帧被丢弃 —— 这是**故意的**，先把最高不确定性（全速端口选对没有）单独验掉。

**Files:**
- Create: `components/packages/tab5-all-in-one/firmware/.gitignore`
- Create: `components/packages/tab5-all-in-one/firmware/CMakeLists.txt`
- Create: `components/packages/tab5-all-in-one/firmware/sdkconfig.defaults`
- Create: `components/packages/tab5-all-in-one/firmware/partitions.csv`
- Create: `components/packages/tab5-all-in-one/firmware/main/CMakeLists.txt`
- Create: `components/packages/tab5-all-in-one/firmware/main/idf_component.yml`
- Create: `components/packages/tab5-all-in-one/firmware/main/gud_protocol.h`（拷贝）
- Create: `components/packages/tab5-all-in-one/firmware/main/lz4.c` / `lz4.h`（拷贝）
- Create: `components/packages/tab5-all-in-one/firmware/main/gud_device.c` / `.h`（拷贝 + 改）
- Create: `components/packages/tab5-all-in-one/firmware/main/tab5_pins.h`
- Create: `components/packages/tab5-all-in-one/firmware/main/usb_descriptors.c` / `.h`
- Create: `components/packages/tab5-all-in-one/firmware/main/app_main.c`

- [ ] **Step 1：定义成功判据**

烧录后在 Linux 主机上：

```
lsusb | grep 16d0                       # 见 16d0:10a9
sudo dmesg | grep -iE "gud|drm"         # 见 gud 绑定、[drm] Initialized gud
ls /dev/dri/                            # 见 cardN
```

且 Tab5 的 UART0（G37/G38，115200 8N1）能看到固件日志 `tab5_aio: tinyusb installed (GUD only)`。

- [ ] **Step 2：建目录并拷贝可复用文件**

```bash
mkdir -p components/packages/tab5-all-in-one/firmware/main
SRC=components/packages/cardputer-all-in-one/firmware
DST=components/packages/tab5-all-in-one/firmware
cp $SRC/main/gud_protocol.h $SRC/main/lz4.c $SRC/main/lz4.h \
   $SRC/main/gud_device.c $SRC/main/gud_device.h $DST/main/
cp $SRC/.gitignore $DST/.gitignore
```

> 不拷 `tinyusb_config/tusb_config.h`，理由见上表。

- [ ] **Step 3：写 `firmware/CMakeLists.txt`**

```cmake
cmake_minimum_required(VERSION 3.16)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(tab5_aio)
```

- [ ] **Step 4：写 `firmware/partitions.csv`**

factory 放大到 4 MB（P4 + DSI + PPA + 后续 UAC/UVC 代码量远大于 Cardputer）：

```
# Name,   Type, SubType, Offset,  Size
nvs,      data, nvs,     0x9000,  0x6000
phy_init, data, phy,     0xf000,  0x1000
factory,  app,  factory, 0x10000, 0x400000
```

- [ ] **Step 5：写 `firmware/sdkconfig.defaults`**

```
CONFIG_IDF_TARGET="esp32p4"
CONFIG_ESPTOOLPY_FLASHSIZE_16MB=y
CONFIG_PARTITION_TABLE_CUSTOM=y
CONFIG_PARTITION_TABLE_CUSTOM_FILENAME="partitions.csv"
CONFIG_FREERTOS_HZ=1000
# Tab5 的 UART0(G37/G38) 引到 M5-Bus，不与显示/音频争引脚，保留完整串口控制台
# （与 Cardputer 的 CONFIG_ESP_CONSOLE_NONE 相反）。
CONFIG_ESP_CONSOLE_UART_DEFAULT=y
# TinyUSB vendor 类：esp_tinyusb 用 *_COUNT(int) 启用，>0 即开启 CFG_TUD_VENDOR
CONFIG_TINYUSB_VENDOR_COUNT=1
# 32MB Octal PSRAM：DPI 帧缓冲(1.84MB) + GUD 收帧缓冲都放这里
CONFIG_SPIRAM=y
CONFIG_SPIRAM_MODE_HEX=y
CONFIG_SPIRAM_SPEED_200M=y
```

> PSRAM 的 mode / speed 若在 Step 9 启动时报错（`psram: PSRAM ID read error`），
> 依次试 `CONFIG_SPIRAM_MODE_OCT=y` + `CONFIG_SPIRAM_SPEED_120M=y`，
> 以实际启动日志里 `Found <N>MB PSRAM` 为准，把可用的组合写死回本文件。

- [ ] **Step 6：写 `firmware/main/idf_component.yml`**

```yaml
dependencies:
  # 与 cardputer-all-in-one 同版本精确锁定，避免描述符/API 漂移。
  espressif/esp_tinyusb: "2.2.1"
  espressif/tinyusb: "0.21.0~1"
```

> 面板与 IO 扩展组件在 Task 2 才加，本任务保持依赖最小。

- [ ] **Step 7：写 `firmware/main/CMakeLists.txt`**

P0 不需要 Cardputer 那 21 行 tusb_config.h 注入块（它只为开 `CFG_TUD_AUDIO`；vendor
类由 `CONFIG_TINYUSB_VENDOR_COUNT=1` 经 esp_tinyusb 自带配置生效）。`PRIV_REQUIRES`
也留空——Task 2 再按实际用到的驱动加：

```cmake
idf_component_register(SRCS "app_main.c" "usb_descriptors.c" "gud_device.c" "lz4.c"
                       INCLUDE_DIRS ".")

# 官方 LZ4 v1.9.4 参考实现(lz4/lz4, BSD-2-Clause)，仅用 LZ4_decompress_safe 解 GUD
# host 端 LZ4 压缩帧。第三方源码放宽告警，避免 main 的 -Werror 因其内部告警失败。
set_source_files_properties(lz4.c PROPERTIES COMPILE_FLAGS "-Wno-error -Wno-unused-function")
```

- [ ] **Step 8：写 `firmware/main/tab5_pins.h`**

```c
#pragma once
/*
 * M5Stack Tab5 板级常量。
 * 引脚值取自 esp-bsp bsp/m5stack_tab5（Apache-2.0）与官方原理图，勿凭记忆改。
 */

/* 内部 I2C：IO 扩展 / 触摸 / 音频 codec / IMU / RTC 共用 */
#define PIN_I2C_SDA        31
#define PIN_I2C_SCL        32

/* 显示 */
#define PIN_LCD_BL         22    /* 背光 LEDA */
#define IOEXP_ADDR         0x43  /* PI4IOE5V6408-1：管 LCD/TOUCH/SPEAKER/CAMERA 使能 */

/* 面板原生分辨率（竖屏）与 DSI 参数 */
#define PANEL_W            720
#define PANEL_H            1280
#define DSI_LANE_NUM       2
#define DSI_LANE_MBPS      1000
#define DSI_PHY_LDO_CHAN   3     /* LDO_VO3 → VDD_MIPI_DPHY */
#define DSI_PHY_LDO_MV     2500

/*
 * 对 host 声明的 GUD 分辨率（横向）。USB-C 只有 12 Mbps 全速，720p 整帧 1.84MB
 * 约需 1.8 秒，交互不可用；640×360 整帧 460KB，且相对面板恰为整数 2 倍，
 * PPA 放大无插值伪影。GUD_W*2 == PANEL_H、GUD_H*2 == PANEL_W（因为要旋转 90°）。
 */
#define GUD_W              640
#define GUD_H              360
#define GUD_SCALE          2

_Static_assert(GUD_W * GUD_SCALE == PANEL_H, "GUD 宽度放大后应等于面板高度(旋转 90°)");
_Static_assert(GUD_H * GUD_SCALE == PANEL_W, "GUD 高度放大后应等于面板宽度(旋转 90°)");
```

- [ ] **Step 9：写 `firmware/main/usb_descriptors.h`**

```c
#pragma once
#include "tusb.h"

/* mainline drm/gud 驱动绑定的固定 VID/PID，不可更改 */
#define GUD_VID 0x16d0
#define GUD_PID 0x10a9

/* 接口编号。后续阶段在 VENDOR 之后追加 UAC / HID / UVC，勿改 VENDOR=0。 */
enum { ITF_NUM_VENDOR = 0, ITF_NUM_TOTAL };

/* 端点编号。P4 全速控制器 ep_count=7 / ep_in_count=5(含 EP0)。 */
#define EPNUM_VENDOR_OUT 0x01
#define EPNUM_VENDOR_IN  0x81

/*
 * 描述符数据由 esp_tinyusb 经 tinyusb_config_t 注入；不要在本工程实现
 * tud_descriptor_*_cb，否则与 esp_tinyusb 的实现重复符号。
 */
extern const tusb_desc_device_t aio_desc_device;
extern const uint8_t aio_desc_configuration[];
extern const char *aio_string_desc_arr[];
extern const int aio_string_desc_count;
```

- [ ] **Step 10：写 `firmware/main/usb_descriptors.c`**

```c
#include "usb_descriptors.h"

/* 设备描述符：Misc/IAD 复合设备，VID/PID = 16d0:10a9（gud 绑定所需） */
const tusb_desc_device_t aio_desc_device = {
    .bLength = sizeof(tusb_desc_device_t),
    .bDescriptorType = TUSB_DESC_DEVICE,
    .bcdUSB = 0x0200,
    .bDeviceClass = TUSB_CLASS_MISC,
    .bDeviceSubClass = MISC_SUBCLASS_COMMON,
    .bDeviceProtocol = MISC_PROTOCOL_IAD,
    .bMaxPacketSize0 = CFG_TUD_ENDPOINT0_SIZE,
    .idVendor = GUD_VID,
    .idProduct = GUD_PID,
    .bcdDevice = 0x0100,
    .iManufacturer = 0x01,
    .iProduct = 0x02,
    .iSerialNumber = 0x03,
    .bNumConfigurations = 0x01,
};

/* 配置描述符：目前只有 IF0 = GUD vendor。 */
#define CONFIG_TOTAL_LEN (TUD_CONFIG_DESC_LEN + TUD_VENDOR_DESC_LEN)
const uint8_t aio_desc_configuration[] = {
    TUD_CONFIG_DESCRIPTOR(1, ITF_NUM_TOTAL, 0, CONFIG_TOTAL_LEN, 0x00, 100),
    TUD_VENDOR_DESCRIPTOR(ITF_NUM_VENDOR, 0, EPNUM_VENDOR_OUT, EPNUM_VENDOR_IN, 64),
};

_Static_assert(sizeof(aio_desc_configuration) == CONFIG_TOTAL_LEN,
               "USB 配置描述符长度不一致");

/* 字符串描述符：UTF-16 转换与 langid 由 esp_tinyusb 完成。 */
static const char k_langid[] = {0x09, 0x04, 0x00};
const char *aio_string_desc_arr[] = {
    k_langid,
    "flange",
    "Tab5 GUD Display",
    "TAB5-0001",
};
const int aio_string_desc_count = sizeof(aio_string_desc_arr) / sizeof(aio_string_desc_arr[0]);
```

- [ ] **Step 11：改 `firmware/main/gud_device.c` 的三处**

改动 1 —— 头部 include 与尺寸来源，把
```c
#include "cardputer_pins.h" /* LCD_W / LCD_H */
#include "display_st7789.h" /* display_blit */
...
#define GUD_W LCD_W
#define GUD_H LCD_H
```
换成（`GUD_W`/`GUD_H` 已在 `tab5_pins.h` 定义，删掉这两行 `#define`）：
```c
#include "tab5_pins.h"   /* GUD_W / GUD_H */
#include "display_dsi.h" /* display_blit */
```

改动 2 —— 模式时序按 640×360 重算。把 `k_mode` 整体替换为：
```c
/*
 * 单显示模式 640x360（面板 720x1280 竖屏，由 PPA 放大 2× 并旋转 90° 铺满）。
 * 时序填合理值：htotal/vtotal 必须 > 显示尺寸，否则被 drm_mode_validate_basic 剪除。
 * clock(kHz) 取 ~60Hz：htotal=680, vtotal=370 → 680*370=251600 px/frame;
 * *60Hz/1000 ≈ 15096 kHz。标记 PREFERRED 让 userspace 自动选中此唯一模式。
 */
static const struct gud_display_mode_req k_mode = {
    .clock = 15096,
    .hdisplay = GUD_W,
    .hsync_start = GUD_W + 8,
    .hsync_end = GUD_W + 16,
    .htotal = GUD_W + 40,
    .vdisplay = GUD_H,
    .vsync_start = GUD_H + 2,
    .vsync_end = GUD_H + 4,
    .vtotal = GUD_H + 10,
    .flags = GUD_DISPLAY_MODE_FLAG_PREFERRED,
};
```

改动 3 —— **删掉 byteswap**。把 `gud_consume_rx_chunk()` 里这一整段（含上方长注释）
```c
        uint16_t *px = (uint16_t *)s_fb;
        uint32_t npx = s_frame_length / 2;
        for (uint32_t i = 0; i < npx; i++) {
            px[i] = __builtin_bswap16(px[i]);
        }
```
替换为一行注释：
```c
        /* 无需 byteswap：DSI/DPI 链路按小端 RGB565 直接取用（BSP_LCD_BIGENDIAN=0），
         * 与 Cardputer 的 ST7789 4-line SPI 不同。 */
```

改动 4 —— **帧缓冲改 PSRAM 运行时分配**。Cardputer 的 240×135 下 `s_fb`/`s_cbuf`
各 63 KB，放内部 SRAM 没问题；改成 640×360 后各 460 KB、合计 900 KB，
**超出 P4 内部 SRAM，链接期直接报 `region 'sram_seg' overflowed`**。把
```c
static uint8_t s_fb[GUD_FB_CAP];
static uint8_t s_cbuf[GUD_FB_CAP];
```
改为
```c
static uint8_t *s_fb;
static uint8_t *s_cbuf;
```
并在 `gud_device_init()` 开头加：
```c
    s_fb = heap_caps_malloc(GUD_FB_CAP, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    s_cbuf = heap_caps_malloc(GUD_FB_CAP, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    assert(s_fb && s_cbuf);
```
同时加 `#include "esp_heap_caps.h"` 与 `#include <assert.h>`。

> 不要改用 `linker.lf` + `CONFIG_SPIRAM_ALLOW_BSS_SEG_EXTERNAL_MEMORY` 的
> extram_bss 映射来解决 —— 那是另一套机制，与本行的 heap 分配重复，且把
> 缓冲的位置决定权从代码挪到链接脚本，后续 Task 增删缓冲时容易漏改。

- [ ] **Step 12：写 `firmware/main/display_dsi.h`（本任务先给桩）**

```c
#pragma once
#include "esp_err.h"

esp_err_t display_init(void);
/* 把一块 GUD 坐标系（640×360 横向）内的 RGB565 矩形送上屏。 */
void display_blit(int x, int y, int w, int h, const void *pixels);
```

- [ ] **Step 13：写 `firmware/main/display_dsi.c` 的桩实现**

本任务不点屏，只让链路能编能跑，把收帧证明打到 UART：

```c
#include "display_dsi.h"
#include "esp_log.h"

static const char *TAG = "disp";

esp_err_t display_init(void)
{
    ESP_LOGW(TAG, "display stub: 面板未初始化（Task 2 实现）");
    return ESP_OK;
}

void display_blit(int x, int y, int w, int h, const void *pixels)
{
    (void)pixels;
    ESP_LOGI(TAG, "blit stub %dx%d @(%d,%d)", w, h, x, y);
}
```

把 `display_dsi.c` 加进 `main/CMakeLists.txt` 的 SRCS。

- [ ] **Step 14：写 `firmware/main/app_main.c`**

**注意 `TINYUSB_CONFIG_FULL_SPEED`，不要用 `TINYUSB_DEFAULT_CONFIG`。**

```c
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "tinyusb.h"
#include "tinyusb_default_config.h"
#include "display_dsi.h"
#include "usb_descriptors.h"
#include "gud_device.h"

static const char *TAG = "tab5_aio";

void app_main(void)
{
    ESP_ERROR_CHECK(display_init());

    /* GUD 控制协议状态机初始化（须在 TinyUSB 安装前，回调可能立即触发） */
    gud_device_init();

    /*
     * ⚠️ 必须显式选全速端口。Tab5 的 USB-C 接在 P4 的 USB1P1 全速 PHY(GPIO24/25)
     * 上，高速 PHY(USB2_OTG_D±) 接的是 USB-A 母座。而 esp_tinyusb 2.2.1 的
     * TINYUSB_DEFAULT_CONFIG() 在 ESP32-P4 上默认展开为 HIGH_SPEED —— 用默认值
     * 会驱动错的 PHY，USB-C 永远枚举不出来。
     */
    tinyusb_config_t tusb_cfg = TINYUSB_CONFIG_FULL_SPEED(NULL, NULL);
    tusb_cfg.descriptor.device = &aio_desc_device;
    tusb_cfg.descriptor.full_speed_config = aio_desc_configuration;
    tusb_cfg.descriptor.string = aio_string_desc_arr;
    tusb_cfg.descriptor.string_count = aio_string_desc_count;
    ESP_ERROR_CHECK(tinyusb_driver_install(&tusb_cfg));
    ESP_LOGI(TAG, "tinyusb installed (GUD only)");

    while (1) vTaskDelay(pdMS_TO_TICKS(1000));
}
```

- [ ] **Step 15：编译**

```bash
get_idf
cd components/packages/tab5-all-in-one/firmware
idf.py set-target esp32p4
idf.py build
```
Expected: `Project build complete.`

- [ ] **Step 16：烧录并在主机验证（人工控制者执行）**

1. 按住 **BOOT(G35)** 同时插 USB-C / 复位，松开 → ROM 下载模式；
2. `idf.py -p <port> flash`；
3. 拔插一次 USB-C 正常上电；
4. 主机执行 Step 1 的三条命令，逐条对照。

若 `lsusb` 完全看不到设备：先接 UART0(G37/G38) 看固件是否起来；确认
`app_main.c` 用的是 `TINYUSB_CONFIG_FULL_SPEED`。

- [ ] **Step 17：提交**

```bash
git add components/packages/tab5-all-in-one
git commit -m "feat(tab5-fw): 工程骨架 + USB-C 全速端口 GUD 枚举 (P0 Task1)"
```

---

## Task 2：DSI 面板点亮（离线，不涉及 USB）

目标：屏幕亮起并显示固定色条。此任务完全不碰 USB，把面板 bring-up 的风险单独隔离。

**Files:**
- Create: `components/packages/tab5-all-in-one/firmware/main/board_power.c` / `board_power.h`
- Modify: `components/packages/tab5-all-in-one/firmware/main/display_dsi.c`（替换桩实现）
- Modify: `components/packages/tab5-all-in-one/firmware/main/idf_component.yml`
- Modify: `components/packages/tab5-all-in-one/firmware/main/CMakeLists.txt`
- Modify: `components/packages/tab5-all-in-one/firmware/main/app_main.c`

- [ ] **Step 1：定义成功判据**

上电后屏幕显示 4 条竖直色条（红/绿/蓝/白），无花屏、无滚动、颜色正确（红就是红，不是蓝）。
UART 日志见 `disp: panel <型号> 720x1280 ready`。

- [ ] **Step 2：`idf_component.yml` 加 IO 扩展与两个面板驱动**

**两种面板批次都要支持**（运行时探测，见 Step 5），所以两个面板组件都进依赖：

```yaml
dependencies:
  espressif/esp_tinyusb: "2.2.1"
  espressif/tinyusb: "0.21.0~1"
  # PI4IOE5V6408-1(0x43)：LCD/TOUCH 电源使能
  espressif/esp_io_expander_pi4ioe5v6408: "1.0.1"
  # 两种面板批次都支持：运行时按 I2C 探测结果二选一初始化。
  # 两者都只是把我们填好的 dpi_config 转发给 esp_lcd_new_panel_dpi，与 IDF 6.0 兼容。
  espressif/esp_lcd_ili9881c: "1.1.0"
  espressif/esp_lcd_st7123: "1.0.2"
```

- [ ] **Step 3：写 `firmware/main/board_power.h`**

```c
#pragma once
#include "esp_err.h"
#include "driver/i2c_master.h"

/* 初始化内部 I2C 总线(G31/G32) 与 PI4IOE5V6408-1，并给面板/触摸上电。 */
esp_err_t board_power_init(void);

/* 内部 I2C 总线句柄，供触摸/codec 等后续阶段复用。 */
i2c_master_bus_handle_t board_i2c_bus(void);
```

- [ ] **Step 4：写 `firmware/main/board_power.c`**

```c
#include "board_power.h"
#include "tab5_pins.h"
#include "driver/gpio.h"
#include "esp_io_expander_pi4ioe5v6408.h"
#include "esp_check.h"
#include "esp_log.h"

static const char *TAG = "board";
static i2c_master_bus_handle_t s_i2c;
static esp_io_expander_handle_t s_ioexp;

i2c_master_bus_handle_t board_i2c_bus(void) { return s_i2c; }

/* 把一个 expander 引脚配成推挽输出并置电平。pin 是掩码(IO_EXPANDER_PIN_NUM_x)。 */
static esp_err_t ioexp_out(uint32_t pin, uint8_t level)
{
    ESP_RETURN_ON_ERROR(esp_io_expander_set_dir(s_ioexp, pin, IO_EXPANDER_OUTPUT),
                        TAG, "ioexp dir");
    ESP_RETURN_ON_ERROR(esp_io_expander_set_output_mode(s_ioexp, pin,
                        IO_EXPANDER_OUTPUT_MODE_PUSH_PULL), TAG, "ioexp mode");
    ESP_RETURN_ON_ERROR(esp_io_expander_set_level(s_ioexp, pin, level),
                        TAG, "ioexp level");
    return ESP_OK;
}

esp_err_t board_power_init(void)
{
    i2c_master_bus_config_t bus_cfg = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = PIN_I2C_SDA,
        .scl_io_num = PIN_I2C_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    ESP_RETURN_ON_ERROR(i2c_new_master_bus(&bus_cfg, &s_i2c), TAG, "i2c bus");

    ESP_RETURN_ON_ERROR(esp_io_expander_new_i2c_pi4ioe5v6408(s_i2c, IOEXP_ADDR, &s_ioexp),
                        TAG, "pi4ioe5v6408");

    /* 面板与触摸上电。触摸本阶段不用，但与面板同源，一并拉起避免后续再动时序。 */
    ESP_RETURN_ON_ERROR(ioexp_out(IO_EXPANDER_PIN_NUM_4, 1), TAG, "LCD_EN");
    ESP_RETURN_ON_ERROR(ioexp_out(IO_EXPANDER_PIN_NUM_5, 1), TAG, "TOUCH_EN");

    /* 背光常亮。需要调光时再换 LEDC PWM，本阶段不做。 */
    gpio_config_t bl = { .mode = GPIO_MODE_OUTPUT, .pin_bit_mask = 1ULL << PIN_LCD_BL };
    ESP_RETURN_ON_ERROR(gpio_config(&bl), TAG, "bl gpio");
    gpio_set_level(PIN_LCD_BL, 1);

    ESP_LOGI(TAG, "board power ready (i2c %d/%d, ioexp 0x%02x)",
             PIN_I2C_SDA, PIN_I2C_SCL, IOEXP_ADDR);
    return ESP_OK;
}
```

- [ ] **Step 5：面板型号的运行时探测**

Tab5 随批次装两种面板，**同一份固件要都支持**，所以型号不能在编译期定死，
在 `display_dsi.c` 里做运行时探测：

```c
/* 面板/触摸控制器随 Tab5 批次而异，用内部 I2C 上的地址区分：
 *   0x55 ⇒ ST7123（显示触控一体）
 *   0x14 ⇒ GT911 触摸，面板为 ILI9881C
 * 两条初始化路径都编进固件，探到哪个走哪个。 */
typedef enum { PANEL_ILI9881C, PANEL_ST7123 } panel_kind_t;

static panel_kind_t panel_detect(void)
{
    if (i2c_master_probe(board_i2c_bus(), 0x55, 100) == ESP_OK)
        return PANEL_ST7123;
    return PANEL_ILI9881C;   /* 探不到 0x55 一律按 ILI9881C（0x14 GT911）处理 */
}
```

`board_power.c` 已在 Step 3/4 就绪，`board_i2c_bus()` 可用。

**另外**：Task 2 期间在 `app_main()` 里保留一段**首次 bring-up 用的 I2C 全扫描**，
用于确认 I2C 总线本身工作正常、并记录本机实际的设备地址表（Step 10 删掉）：

```c
    for (uint8_t a = 0x08; a < 0x78; a++) {
        if (i2c_master_probe(board_i2c_bus(), a, 50) == ESP_OK)
            ESP_LOGI("i2cscan", "found 0x%02x", a);
    }
```

预期能看到：0x43/0x44 IO 扩展、0x10 ES8388、0x40 ES7210、0x68 BMI270、
0x32 RX8130CE、0x41 INA226，外加 0x14 或 0x55 之一。把实际结果记进 README。

- [ ] **Step 6：写 `firmware/main/display_dsi.c` 的真实实现（暂不含 PPA）**

```c
/*
 * M5Stack Tab5 显示 HAL。面板原生 720x1280 竖屏，MIPI-DSI 2 lane @ 1Gbps。
 * DSI/DPI 参数复刻自 esp-bsp bsp/m5stack_tab5/src/bsp_display.c（Apache-2.0）。
 * Tab5 随批次装 ILI9881C 或 ST7123 两种面板，两条路径都编进固件，
 * 由 panel_detect() 在运行时按内部 I2C 上的地址区分。
 */
#include "display_dsi.h"
#include "tab5_pins.h"
#include "board_power.h"
#include "esp_ldo_regulator.h"
#include "esp_lcd_mipi_dsi.h"
#include "esp_lcd_panel_dev.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_ili9881c.h"
#include "esp_lcd_st7123.h"
#include "esp_check.h"
#include "esp_log.h"
#include <string.h>

static const char *TAG = "disp";

static esp_ldo_channel_handle_t s_ldo;
static esp_lcd_dsi_bus_handle_t s_dsi_bus;
static esp_lcd_panel_io_handle_t s_io;
static esp_lcd_panel_handle_t s_panel;
static uint16_t *s_fb;      /* DPI 帧缓冲，720x1280 RGB565，由驱动分配在 PSRAM */

uint16_t *display_frame_buffer(void) { return s_fb; }

esp_err_t display_init(void)
{
    /* MIPI DSI PHY 供电：内部 LDO_VO3 @ 2.5V。不做这步 DSI 停在 "No Power" 态。 */
    esp_ldo_channel_config_t ldo_cfg = {
        .chan_id = DSI_PHY_LDO_CHAN,
        .voltage_mv = DSI_PHY_LDO_MV,
    };
    ESP_RETURN_ON_ERROR(esp_ldo_acquire_channel(&ldo_cfg, &s_ldo), TAG, "dsi phy ldo");

    esp_lcd_dsi_bus_config_t bus_cfg = {
        .bus_id = 0,
        .num_data_lanes = DSI_LANE_NUM,
        .phy_clk_src = MIPI_DSI_PHY_CLK_SRC_DEFAULT,
        .lane_bit_rate_mbps = DSI_LANE_MBPS,
    };
    ESP_RETURN_ON_ERROR(esp_lcd_new_dsi_bus(&bus_cfg, &s_dsi_bus), TAG, "dsi bus");

    esp_lcd_dbi_io_config_t dbi_cfg = {
        .virtual_channel = 0,
        .lcd_cmd_bits = 8,
        .lcd_param_bits = 8,
    };
    ESP_RETURN_ON_ERROR(esp_lcd_new_panel_io_dbi(s_dsi_bus, &dbi_cfg, &s_io), TAG, "dbi io");

    /*
     * DPI 配置。两种面板只有像素时钟与 porch 不同，其余一致。
     * IDF 6.0：用 in/out_color_format，没有 5.x 的 .pixel_format 字段。
     */
    esp_lcd_dpi_panel_config_t dpi_cfg = {
        .virtual_channel = 0,
        .dpi_clk_src = MIPI_DSI_DPI_CLK_SRC_DEFAULT,
        .in_color_format = LCD_COLOR_FMT_RGB565,
        .out_color_format = LCD_COLOR_FMT_RGB565,
        .num_fbs = 1,
        .video_timing = { .h_size = PANEL_W, .v_size = PANEL_H },
    };

    const panel_kind_t kind = panel_detect();
    if (kind == PANEL_ST7123) {
        dpi_cfg.dpi_clock_freq_mhz = 70;
        dpi_cfg.video_timing.hsync_back_porch  = 40;
        dpi_cfg.video_timing.hsync_pulse_width = 2;
        dpi_cfg.video_timing.hsync_front_porch = 40;
        dpi_cfg.video_timing.vsync_back_porch  = 8;
        dpi_cfg.video_timing.vsync_pulse_width = 2;
        dpi_cfg.video_timing.vsync_front_porch = 220;
    } else {
        dpi_cfg.dpi_clock_freq_mhz = 60;
        dpi_cfg.video_timing.hsync_back_porch  = 140;
        dpi_cfg.video_timing.hsync_pulse_width = 40;
        dpi_cfg.video_timing.hsync_front_porch = 40;
        dpi_cfg.video_timing.vsync_back_porch  = 20;
        dpi_cfg.video_timing.vsync_pulse_width = 4;
        dpi_cfg.video_timing.vsync_front_porch = 20;
    }

    esp_lcd_panel_dev_config_t panel_cfg = {
        .reset_gpio_num = -1,          /* Tab5 面板无独立 reset 脚 */
        .rgb_ele_order = LCD_RGB_ELEMENT_ORDER_RGB,
        .bits_per_pixel = 16,
    };

    /*
     * 两个 vendor config 结构不同：ili9881c 的 mipi_config 有 lane_num 字段，
     * st7123 的没有（只有 dsi_bus + dpi_config）。照抄另一个会编译失败。
     */
    if (kind == PANEL_ST7123) {
        static st7123_vendor_config_t vendor_st7123;
        vendor_st7123 = (st7123_vendor_config_t){
            .mipi_config = { .dsi_bus = s_dsi_bus, .dpi_config = &dpi_cfg },
        };
        panel_cfg.vendor_config = &vendor_st7123;
        ESP_RETURN_ON_ERROR(esp_lcd_new_panel_st7123(s_io, &panel_cfg, &s_panel),
                            TAG, "new panel st7123");
    } else {
        static ili9881c_vendor_config_t vendor_ili9881c;
        vendor_ili9881c = (ili9881c_vendor_config_t){
            .mipi_config = { .dsi_bus = s_dsi_bus, .dpi_config = &dpi_cfg,
                             .lane_num = DSI_LANE_NUM },
        };
        panel_cfg.vendor_config = &vendor_ili9881c;
        ESP_RETURN_ON_ERROR(esp_lcd_new_panel_ili9881c(s_io, &panel_cfg, &s_panel),
                            TAG, "new panel ili9881c");
    }

    ESP_RETURN_ON_ERROR(esp_lcd_panel_reset(s_panel), TAG, "panel reset");
    ESP_RETURN_ON_ERROR(esp_lcd_panel_init(s_panel), TAG, "panel init");
    ESP_RETURN_ON_ERROR(esp_lcd_panel_disp_on_off(s_panel, true), TAG, "disp on");

    ESP_RETURN_ON_ERROR(esp_lcd_dpi_panel_get_frame_buffer(s_panel, 1, (void **)&s_fb),
                        TAG, "get fb");
    memset(s_fb, 0, (size_t)PANEL_W * PANEL_H * 2);

    ESP_LOGI(TAG, "panel %s %dx%d ready, fb=%p",
             kind == PANEL_ST7123 ? "ST7123" : "ILI9881C", PANEL_W, PANEL_H, s_fb);
    return ESP_OK;
}

void display_blit(int x, int y, int w, int h, const void *pixels)
{
    /* Task 3 用 PPA 实现。 */
    (void)x; (void)y; (void)w; (void)h; (void)pixels;
}
```

在 `display_dsi.h` 里补上：
```c
#include <stdint.h>
/* DPI 帧缓冲（720×1280 RGB565）。Task 2 的色条自检与 Task 3 的 PPA 目标都用它。 */
uint16_t *display_frame_buffer(void);
```

- [ ] **Step 7：app_main 加上电与色条自检**

在 `app_main()` 开头把 `display_init()` 换成：

```c
    ESP_ERROR_CHECK(board_power_init());
    ESP_ERROR_CHECK(display_init());

    /* 面板自检：4 条竖直色条（面板竖屏坐标系，x 是短边 720） */
    uint16_t *fb = display_frame_buffer();
    const uint16_t bars[4] = {0xF800, 0x07E0, 0x001F, 0xFFFF}; /* R G B W (RGB565) */
    for (int y = 0; y < PANEL_H; y++)
        for (int x = 0; x < PANEL_W; x++)
            fb[y * PANEL_W + x] = bars[(x * 4) / PANEL_W];
```

并加上 `#include "tab5_pins.h"`（`board_power.h` 在 Step 5 已经加过）。
`main/CMakeLists.txt` 的 `PRIV_REQUIRES` 再补上 `esp_lcd`（`esp_driver_i2c` 在 Step 5 已加）：

```cmake
                       PRIV_REQUIRES esp_driver_gpio esp_driver_i2c esp_lcd)
```

- [ ] **Step 8：编译**

```bash
get_idf && cd components/packages/tab5-all-in-one/firmware && idf.py build
```
Expected: `Project build complete.`

- [ ] **Step 9：上板验证（人工控制者执行）**

烧录后看屏。三种典型失败与处置：

| 现象 | 处置 |
|---|---|
| 全黑、UART 报 `dsi phy ldo` 失败 | 确认 `chan_id=3`；`CONFIG_ESP_LDO_CHAN3_*` 是否被其它配置占用 |
| 全黑、日志正常走完 | 检查 `LCD_EN`（expander 0x43 pin4）与背光 G22；用万用表量背光 |
| 有画面但花屏/条纹/滚动 | 面板 init 命令不匹配（组件自带的默认序列与 M5 这块屏对不上）。把 esp-bsp `bsp/m5stack_tab5/priv_include/disp_init_data.h`（ILI9881C）或 `disp_init_data_1.h`（ST7123）的数组 vendor 进本工程（新建 `panel_init_data.h`，注明 Apache-2.0 来源），填进对应 `*_vendor_config_t` 的 `init_cmds` / `init_cmds_size` |
| 红蓝互换 | 把 `rgb_ele_order` 改成 `LCD_RGB_ELEMENT_ORDER_BGR` |
| `panel_detect()` 判错型号 | 看 i2cscan 日志里实际有没有 0x55；若两个地址都在或都不在，改用更强的判据（读控制器 ID 寄存器） |

- [ ] **Step 10：标注未验证路径、删掉扫描代码、提交**

实机只会跑通两条路径中的一条，另一条是「照 esp-bsp 复刻但未上板」的状态。
**必须在日志里说清楚**，否则日后有人会误以为两条都验过：给未走到的那条加一句
warning，例如实机是 ILI9881C 时——

```c
    if (kind == PANEL_ST7123)
        ESP_LOGW(TAG, "ST7123 路径未经实机验证（本项目实机为 ILI9881C）");
```

把实机的 i2cscan 地址表与验证过的面板型号记进 README，然后删掉 Step 5 的临时全扫描
（`panel_detect()` 是常驻功能，**不要删**）。

```bash
git add components/packages/tab5-all-in-one
git commit -m "feat(tab5-fw): MIPI-DSI 面板点亮，双面板批次运行时探测 (P0 Task2)"
```

---

## Task 3：PPA 缩放 + 旋转（把 640×360 铺满面板）

目标：`display_blit()` 真正可用 —— 把 GUD 横向坐标系的一块 RGB565 经 PPA
**2× 缩放 + 90° 旋转**写进 720×1280 的 DPI 帧缓冲，整帧与局部矩形都正确。

**Files:**
- Modify: `components/packages/tab5-all-in-one/firmware/main/display_dsi.c`
- Modify: `components/packages/tab5-all-in-one/firmware/main/app_main.c`（临时自检，Task 4 移除）
- Modify: `components/packages/tab5-all-in-one/firmware/main/CMakeLists.txt`

- [ ] **Step 1：定义成功判据**

用一张 640×360 的自检图（左上红、右上绿、左下蓝、右下白，正中一个 40×40 黑方块）整帧 blit 后：

- 画面**充满全屏**、无黑边、无越界；
- 四个色块与手持横屏方向一致（横屏看时左上就是红）；
- 中央黑方块居中；
- 再单独 blit 一次 `(x=0, y=0, w=64, h=64)` 的纯黄小块，它出现在**横屏视角的左上角**。

> ⚠️ **判读时注意区分「面板坐标」与「观看方位」**。整条链路带 90° 旋转，
> 两者差一个旋转量。黄块在**面板坐标系**里的落点是：
> `DISPLAY_ROT_CCW90=1` → (0, 1152)，面板左下角；`=0` → (592, 0)，面板右上角。
> 横持观看时其中之一会呈现在左上角。**判据以横持观看的方位为准**，
> 不要拿面板坐标去对，否则会误判成 bug。两个分支的落点相差 180°，
> 所以这个开关确实能有效区分。

- [ ] **Step 2：理解坐标变换（写码前先想清楚，这是本任务唯一容易错的地方）**

- GUD 坐标系：横向 640(w) × 360(h)，原点左上。
- 面板坐标系：竖向 720(w) × 1280(h)，原点左上。
- PPA 的 `rotation_angle` 是**逆时针**。输入块 (bx, by, bw, bh) 先按 `scale` 放大成
  (2bw, 2bh)，再整体旋转，落到输出图的 `(block_offset_x, block_offset_y)`。
- 取 90° CCW 时，GUD 的 (x, y) 映射到面板的：
  ```
  panel_x = y * 2
  panel_y = PANEL_H - (x + w) * 2      /* x 轴反向 */
  ```
  输出块尺寸为 `(h*2, w*2)`。
- **旋转方向可能是反的**（取决于面板扫描方向），所以把角度做成一个宏，Step 6 上板二选一：
  ```c
  #define DISPLAY_ROT_CCW90   1   /* 0 = 用 270° */
  ```
  取 270° CCW 时映射为：
  ```
  panel_x = PANEL_W - (y + h) * 2
  panel_y = x * 2
  ```

- [ ] **Step 2.5：cache 一致性 —— PPA 路径不用自己 msync，但有两条约束**

P4 的 DMA 不侦听 cache，所以「谁写缓冲、谁负责回写」这件事必须想清楚。已核实
（`$HOME/esp/esp-idf/components/esp_driver_ppa/src/ppa_srm.c`）：

- `:254` PPA 对**输入**缓冲做 `esp_cache_msync(..., DIR_C2M | UNALIGNED)`（回写 CPU 刚解压的源像素）
- `:260` PPA 对**输出**缓冲做 `esp_cache_msync(..., DIR_M2C)`（invalidate，让 CPU 能读到 DMA 写的新内容）

两者都在提交 DMA 事务前无条件执行 ⇒ **`display_blit()` 里输入输出都不用自己 msync**。

但要守住两条：

1. **交给 PPA 之前，`s_fb` 上不能留 CPU 的脏 cache 行**。`:260` 是 invalidate 不是回写；
   若 CPU 先直写了 `s_fb` 又没 flush，那些脏行可能在 PPA 写完之后才被淘汰，
   **反过来覆盖 PPA 的输出**。Task 2 的 `memset` 与色条自检后都紧跟了
   `display_frame_buffer_flush()`，已无隐患；但今后凡是混用 CPU 直写与 PPA 的地方都要先 flush。
2. `:260` 用 `PPA_ALIGN_DOWN`/`PPA_ALIGN_UP` 把 invalidate 区间**向外扩**到 cache line 边界
   （源码注释：`alignment strict on M2C direction`）。即 PPA 输出块上下边缘所在的
   两条 cache line 会被连带 invalidate —— 又一个「别在相邻区域留脏行」的理由。

> `display_frame_buffer_flush()` 目前是整幅 1.84MB 全 flush，开机只调两次无所谓。
> 若将来出现逐帧的 CPU 直写路径，要改成按行区间 flush（照 IDF
> `esp_lcd_panel_dpi.c:646` 的 `y_start`/`y_end` 算法，届时需加 `UNALIGNED` 标志）。
> 现在不做。

- [ ] **Step 3：在 `display_dsi.c` 里加 PPA client**

在文件顶部加 `#include "driver/ppa.h"`，并加静态句柄：

```c
static ppa_client_handle_t s_ppa;
```

在 `display_init()` 的 `memset(s_fb, ...)` 之后加：

```c
    ppa_client_config_t ppa_cfg = {
        .oper_type = PPA_OPERATION_SRM,
        .max_pending_trans_num = 1,   /* 只用阻塞模式，1 即可 */
    };
    ESP_RETURN_ON_ERROR(ppa_register_client(&ppa_cfg, &s_ppa), TAG, "ppa client");
```

- [ ] **Step 4：实现 `display_blit()`**

替换 Task 2 里的空实现：

```c
/*
 * 把 GUD 坐标系(640×360 横向)的一块 RGB565 送上面板(720×1280 竖向)。
 * PPA 的 SRM 引擎在一次操作里同时完成 2× 缩放与 90° 旋转，无需两遍搬运。
 * 注意 PPA 的 rotation_angle 是逆时针(CCW)。
 */
void display_blit(int x, int y, int w, int h, const void *pixels)
{
    if (!s_ppa || !s_fb) return;

    /* 旋转后输出块的尺寸：宽高互换再各乘 2 */
    const uint32_t out_w = (uint32_t)h * GUD_SCALE;
    const uint32_t out_h = (uint32_t)w * GUD_SCALE;

#if DISPLAY_ROT_CCW90
    const uint32_t out_x = (uint32_t)y * GUD_SCALE;
    const uint32_t out_y = (uint32_t)(PANEL_H - (x + w) * GUD_SCALE);
    const ppa_srm_rotation_angle_t rot = PPA_SRM_ROTATION_ANGLE_90;
#else
    const uint32_t out_x = (uint32_t)(PANEL_W - (y + h) * GUD_SCALE);
    const uint32_t out_y = (uint32_t)x * GUD_SCALE;
    const ppa_srm_rotation_angle_t rot = PPA_SRM_ROTATION_ANGLE_270;
#endif

    ppa_srm_oper_config_t op = {
        .in = {
            .buffer = pixels,
            .pic_w = GUD_W,
            .pic_h = GUD_H,
            .block_w = (uint32_t)w,
            .block_h = (uint32_t)h,
            .block_offset_x = (uint32_t)x,
            .block_offset_y = (uint32_t)y,
            .srm_cm = PPA_SRM_COLOR_MODE_RGB565,
        },
        .out = {
            .buffer = s_fb,
            .buffer_size = (uint32_t)PANEL_W * PANEL_H * 2,
            .pic_w = PANEL_W,
            .pic_h = PANEL_H,
            .block_offset_x = out_x,
            .block_offset_y = out_y,
            .srm_cm = PPA_SRM_COLOR_MODE_RGB565,
        },
        .rotation_angle = rot,
        .scale_x = (float)GUD_SCALE,
        .scale_y = (float)GUD_SCALE,
        .mirror_x = false,
        .mirror_y = false,
        .byte_swap = false,
        .mode = PPA_TRANS_MODE_BLOCKING,
    };

    esp_err_t err = ppa_do_scale_rotate_mirror(s_ppa, &op);
    if (err != ESP_OK)
        ESP_LOGW(TAG, "ppa srm 失败 %s: %dx%d @(%d,%d) → (%u,%u) %ux%u",
                 esp_err_to_name(err), w, h, x, y,
                 (unsigned)out_x, (unsigned)out_y, (unsigned)out_w, (unsigned)out_h);
    (void)out_w; (void)out_h;
}
```

在 `tab5_pins.h` 之后、文件顶部加：
```c
/* 旋转方向按实机标定：1 = 90° CCW，0 = 270° CCW。见 README 的方向标定说明。 */
#define DISPLAY_ROT_CCW90 1
```

- [ ] **Step 5：`main/CMakeLists.txt` 的 `PRIV_REQUIRES` 加 `esp_driver_ppa`**

```cmake
                       PRIV_REQUIRES esp_driver_gpio esp_driver_i2c esp_driver_ppa esp_lcd)
```

- [ ] **Step 6：`display_test_pattern()` 换成 640×360 自检图**

> 实施时的偏离（已采纳）：自检图放在 `display_dsi.c` 的 `display_test_pattern()` 里，
> 不是 `app_main`（Task 2 的接口收窄已把自检收进显示模块，`app_main` 只留一行调用）。
> 另外 640×360×2 = 460 KB **不能放 `.bss`** —— 内部 DRAM 只剩约 565 KB，放进去余量吃掉八成；
> 改用 `heap_caps_malloc(MALLOC_CAP_SPIRAM)` 分配、用完 `heap_caps_free()`。
> 64×64 黄块也不新开缓冲，直接复用 probe 缓冲的左上角子块
> （`display_blit()` 按 `pic_w=GUD_W` 解读输入，取的正是 stride 640 的左上角）。
> 主任务栈只有 `CONFIG_ESP_MAIN_TASK_STACK_SIZE=3584`，8 KB 放栈上会当场爆栈。

逻辑等价于：

```c
    /* PPA 自检：640×360 四象限 + 中央黑方块，整帧 blit 应铺满全屏 */
    static uint16_t probe[GUD_W * GUD_H];
    for (int py = 0; py < GUD_H; py++) {
        for (int px = 0; px < GUD_W; px++) {
            uint16_t c;
            if (py < GUD_H / 2) c = (px < GUD_W / 2) ? 0xF800 : 0x07E0; /* 红 绿 */
            else                c = (px < GUD_W / 2) ? 0x001F : 0xFFFF; /* 蓝 白 */
            probe[py * GUD_W + px] = c;
        }
    }
    for (int py = GUD_H / 2 - 20; py < GUD_H / 2 + 20; py++)
        for (int px = GUD_W / 2 - 20; px < GUD_W / 2 + 20; px++)
            probe[py * GUD_W + px] = 0x0000;
    display_blit(0, 0, GUD_W, GUD_H, probe);

    /* 局部矩形自检：左上角 64×64 纯黄 */
    vTaskDelay(pdMS_TO_TICKS(2000));
    static uint16_t corner[64 * 64];
    for (int i = 0; i < 64 * 64; i++) corner[i] = 0xFFE0; /* 黄 */
    display_blit(0, 0, 64, 64, corner);
```

> `probe` 是 640×360×2 = 460 KB，必须是 `static`（放不进任务栈）。若链接报 DRAM 不足，
> 改成 `heap_caps_malloc(GUD_W * GUD_H * 2, MALLOC_CAP_SPIRAM)` 并加 `#include "esp_heap_caps.h"`。

- [ ] **Step 7：编译**

```bash
get_idf && cd components/packages/tab5-all-in-one/firmware && idf.py build
```
Expected: `Project build complete.`

- [ ] **Step 8：上板标定方向（人工控制者执行）**

烧录后横持 Tab5 观察：

- 四象限方向对、黄块在左上 ⇒ `DISPLAY_ROT_CCW90 1` 正确，保留；
- 画面上下颠倒或黄块跑到右下 ⇒ 改成 `#define DISPLAY_ROT_CCW90 0` 重编再看；
- 两个值都不对（画面被裁一半 / PPA 报错）⇒ 说明 `out_x/out_y` 公式写反了，
  回 Step 2 重推映射，用整帧（x=0,y=0）先对齐再验局部块。

把最终值与结论写进 README。

- [ ] **Step 9：提交**

```bash
git add components/packages/tab5-all-in-one
git commit -m "feat(tab5-fw): PPA 单次操作完成 2x 缩放 + 90 度旋转铺满面板 (P0 Task3)"
```

---

## Task 4：GUD 接入（整帧、未压缩）

目标：host 的 `modetest -M gud` 能把图送上 Tab5 屏幕。

**Files:**
- Modify: `components/packages/tab5-all-in-one/firmware/main/gud_device.c`
- Modify: `components/packages/tab5-all-in-one/firmware/main/app_main.c`（移除 Task 3 自检）

- [ ] **Step 1：定义成功判据**

主机执行：
```bash
modetest -M gud                                   # 列出 connector + 640x360 模式
modetest -M gud -s <connector_id>:640x360         # 送测试图
```
Tab5 屏上出现 modetest 的彩色测试图，铺满全屏、方向与 Task 3 标定一致。

- [ ] **Step 2：确认 `gud_device.c` 的帧缓冲落在 PSRAM**

**已在 Task 1 的「改动 4」完成**（原本排在这里是计划编排错误：`GUD_W/GUD_H` 在 Task 1
就变成 640×360 了，两个缓冲当场涨到 900 KB，Task 1 不做这一步根本链接不过）。

本步只需确认：`s_fb` / `s_cbuf` 是 `uint8_t *`、在 `gud_device_init()` 里用
`heap_caps_malloc(..., MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT)` 分配，且启动日志
无 `region 'sram_seg' overflowed`。若不符，回 Task 1 改动 4 的做法补齐。

- [ ] **Step 3：移除 app_main 的 Task 3 自检**

删掉 `probe` / `corner` 两段自检代码及相关变量，`app_main()` 恢复为
`board_power_init() → display_init() → gud_device_init() → tinyusb_driver_install()`。

保留一句开机提示图（可选）：用 `memset(display_frame_buffer(), 0, PANEL_W*PANEL_H*2)` 清屏即可。

- [ ] **Step 4：编译**

```bash
get_idf && cd components/packages/tab5-all-in-one/firmware && idf.py build
```
Expected: `Project build complete.`

- [ ] **Step 5：上板 + 主机验证（人工控制者执行）**

按 Step 1 执行。若 `modetest -M gud` 列不出 640x360 模式，看 UART 日志里
`gud: ctrl bRequest=...` 序列，重点确认 `GUD_REQ_GET_CONNECTOR_MODES` 有被应答，
以及 `k_mode` 的 `htotal > hdisplay`、`vtotal > vdisplay`（否则被内核剪除）。

- [ ] **Step 6：提交**

```bash
git add components/packages/tab5-all-in-one
git commit -m "feat(tab5-fw): GUD 640x360 模式接通显示链路 (P0 Task4)"
```

---

## Task 5：脏矩形 + LZ4 验证

目标：确认局部更新的坐标变换正确、LZ4 压缩帧解得对。这两条在 Task 4 的整帧路径下
不会被触发，必须单独验。

**Files:**
- Modify: `components/packages/tab5-all-in-one/firmware/main/gud_device.c`（仅可能的日志调整）

- [ ] **Step 1：定义成功判据**

主机用 GStreamer 直驱 GUD 卡跑动态内容（会产生大量脏矩形与 LZ4 压缩帧）：

```bash
# 注意：modetest -s 与 kmssink 都需 DRM master，二选一（先停掉另一个）
gst-launch-1.0 videotestsrc ! videoconvert ! videoscale ! \
  video/x-raw,width=640,height=360 ! \
  kmssink driver-name=gud connector-id=<id> force-modesetting=true
```

判据：画面连续更新、**无错位色块**、无残影、无区域性撕裂；UART 日志里
`LZ4 解压失败` 与 `ppa srm 失败` 均为 0 条。

- [ ] **Step 2：打开脏矩形与压缩的调试日志**

临时把 `gud_device.c` 里 `ESP_LOGD` 的两条（`SET_BUFFER 武装` 与 `帧收满`）
改成 `ESP_LOGI`，或直接在 `sdkconfig.defaults` 加：
```
CONFIG_LOG_MAXIMUM_LEVEL_DEBUG=y
CONFIG_LOG_DEFAULT_LEVEL_DEBUG=y
```
观察日志里出现 `xfer=...(LZ4)` 与非全屏的 `blit WxH @(x,y)`，证明两条路径都被走到。

- [ ] **Step 3：定点验证脏矩形坐标**

若 Step 1 出现错位，用最小复现定位：在主机上只刷一个已知位置的小矩形，
在固件 `display_blit()` 里临时把入参打出来，人工核对
`(x,y,w,h) → (out_x,out_y)` 是否符合 Task 3 Step 2 的公式。
**不要靠猜改公式**，先确认哪个方向偏了多少。

- [ ] **Step 4：关掉调试日志并编译**

把 Step 2 的临时改动还原（`ESP_LOGI` 改回 `ESP_LOGD`、删掉 log level 配置），
避免逐帧日志压垮 UART 影响帧率测量。

```bash
get_idf && cd components/packages/tab5-all-in-one/firmware && idf.py build
```
Expected: `Project build complete.`

- [ ] **Step 5：提交**

```bash
git add components/packages/tab5-all-in-one
git commit -m "feat(tab5-fw): 脏矩形与 LZ4 路径上板验证通过 (P0 Task5)"
```

---

## Task 6：帧率实测 + README + 收尾

目标：把这一阶段的实测数据与操作方法固化成文档，供后续阶段与使用者参考。

**Files:**
- Create: `components/packages/tab5-all-in-one/README.md`
- Create: `components/packages/tab5-all-in-one/firmware/README.md`
- Modify: `docs/superpowers/specs/2026-08-11-tab5-all-in-one-design.md`（回填实测帧率）

- [ ] **Step 1：实测并记录帧率（人工控制者执行）**

跑两个场景，各记一个数：

```bash
# 场景 A：全屏动态内容（帧率下限）
gst-launch-1.0 videotestsrc ! videoconvert ! videoscale ! \
  video/x-raw,width=640,height=360 ! \
  kmssink driver-name=gud connector-id=<id> force-modesetting=true
# 用 GST_DEBUG=kmssink:5 或在固件侧统计 blit 次数/秒

# 场景 B：文本终端（真实使用场景）
# 把 fbcon 绑到 GUD 卡后在上面跑 vim/htop，观察打字与滚动的跟手程度
```

记录：场景 A 的 fps、场景 B 的主观跟手程度（"打字无感延迟 / 滚动可见撕裂" 这类描述）。

- [ ] **Step 2：写 `firmware/README.md`**

必须覆盖这些内容（照 `cardputer-all-in-one/firmware/README.md` 的结构）：

- 能力与接口表（当前只有 IF0 GUD）；
- **烧录要点**：TinyUSB 接管全速 PHY ⇒ 按 BOOT(G35) 进 ROM 下载模式；
- **日志**：UART0 = TX G37 / RX G38（M5-Bus 上），115200；
- **⚠️ 全速端口陷阱**：必须 `TINYUSB_CONFIG_FULL_SPEED`，否则驱动到 USB-A 那条高速 PHY；
- **为什么是 640×360**：USB-C 全速 12 Mbps + 面板 720×1280 竖屏，PPA 单次操作缩放+旋转；
- **方向标定**：`DISPLAY_ROT_CCW90` 的含义与本机取值；
- 面板型号（Task 2 Step 2 的实测结论）与 DPI 时序表；
- host 侧验证命令（`lsusb` / `dmesg` / `modetest` / `gst-launch-1.0`）；
- Step 1 实测的帧率数据；
- 文件职责表。

- [ ] **Step 3：写包级 `README.md`**

照 `cardputer-all-in-one/README.md` 的结构：两侧分工表、当前状态清单
（✅ GUD 显示 / ⏳ 键盘、触摸、音频、UVC）、文档链接（本 spec 与 plan）。

- [ ] **Step 4：把实测帧率回填进 spec §11 的风险表**

把「640×360 放大后文字发虚」与「实测帧率」两行的结论按实际情况更新，
若帧率不可接受则在 spec 里记录下一步方案（spec §11 已给出回退选项）。

- [ ] **Step 5：提交并打 tag**

```bash
git add components/packages/tab5-all-in-one docs/superpowers/specs/2026-08-11-tab5-all-in-one-design.md
git commit -m "docs(tab5): P0 GUD 显示 README 与实测帧率回填 (P0 Task6)"
git tag tab5-gud-display
```

---

## 自查（写完计划后回看 spec 的覆盖情况）

| spec 章节 | 覆盖任务 |
|---|---|
| §1.2 三条硬约束 | Task 1（全速端口、BOOT 烧录、UART 日志）；端点预算在「关键事实」中给出具体数字 |
| §2 USB 布局 | Task 1（IF0 GUD）；IF1–IF6 属后续阶段计划 |
| §3.1 为什么 640×360 | Task 1 Step 8（`tab5_pins.h` 注释 + 静态断言） |
| §3.2 流水线 / 删 byteswap / 脏矩形 | Task 1 Step 11（删 byteswap）、Task 3（PPA）、Task 5（脏矩形） |
| §3.3 面板 bring-up | Task 2（含面板型号实测与 init 命令 fallback） |
| §8 工程结构 | Task 1–3 建齐 |
| §8.1 依赖 | Task 1 Step 6、Task 2 Step 3（只加面板 + IO expander） |
| §8.2 sdkconfig | Task 1 Step 5 |
| §8.3 烧录 | Task 1 Step 16、Task 6 Step 2 |
| §10 阶段 0 / 阶段 1 验证标准 | Task 1 Step 1、Task 4 Step 1、Task 5 Step 1、Task 6 Step 1 |
| §4 键盘 / §5 触摸 / §6 音频 / §7 UVC / §9 主机侧 | **不在本计划范围**，各自另立计划 |
