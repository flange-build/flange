# Cardputer USB 一线通 — P0：GUD 显示链路打通 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: 用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实施。步骤用 `- [ ]` 复选框跟踪。

**Goal:** 让 M5Stack Cardputer（ESP32-S3）作为 USB 设备，通过一根 USB 线被 Linux 主机的 mainline `gud` 驱动识别为 DRM 显示器（`/dev/dri/cardN`），并能用 `modetest` 把画面送上 Cardputer 的 240×135 屏。

**Architecture:** ESP-IDF + TinyUSB 实现一个 vendor-class USB 设备（VID/PID 必须是 GUD 官方的 `0x16D0/0x10A9`，否则 host `gud` 不绑定），固件实现 GUD 设备协议的最小子集（控制请求 + bulk OUT 收帧，**P0 暂不压缩**），收到的 RGB565 帧经 `esp_lcd` 经 SPI blit 到 ST7789。Host 侧零自定义驱动。

**Tech Stack:** ESP-IDF v5.5.1（`get_idf_551`）、TinyUSB（vendor class）、`esp_lcd`（ST7789）、FreeRTOS；host 侧 mainline `gud` + `modetest`。

---

## 范围与分期说明

本计划**只覆盖 P0**（设计文档 §8 的第一阶段）。后续 P1–P5 各自独立成计划，在 P0 落地后再写——因为它们的细节依赖 P0 的实测结果（确切 GPIO、模组是否带 PSRAM、GUD 协议常量、`esp_tinyusb` 是否暴露 vendor class）。P1–P5 概要见文末「后续计划」。

设计来源：`docs/superpowers/specs/2026-06-14-cardputer-usb-all-in-one-design.md`。

## 本计划的「测试」哲学（嵌入式适配）

固件没有 pytest 回路，**测试预言机是 host 侧命令 + 物理屏幕观察**。每个任务先定义**可观测的成功判据**（确切命令 + 期望输出），再实现，再运行判据。固件日志：一旦 TinyUSB 接管 native USB（Task 2 起），USB-C 上的串口控制台消失，**固件日志改走 UART0（GPIO43=U0TXD / GPIO44=U0RXD），接 USB-UART 转接器 @115200**；在那之前用 `idf.py monitor`（USB-Serial-JTAG）即可。

## 已确认的硬事实（来自调研，勿改）

- **gud 绑定条件**（本机 `modinfo gud` 实测）：`usb:v16D0p10A9...icFF...` → 设备描述符必须 `idVendor=0x16D0, idProduct=0x10A9`，且至少一个接口 `bInterfaceClass=0xFF`。
- **P0 可在本开发机验证**：本机 `/lib/modules/6.8.0-124-generic/.../gud.ko` 存在。需补装 `modetest`（见 Task 3 步骤）。
- **GUD 协议头**：`include/drm/gud.h`（Dual MIT/GPL，可复制）+ 参考实现 `https://github.com/notro/gud`。

## 文件结构（P0 子集）

```
components/packages/cardputer-all-in-one/firmware/
├── CMakeLists.txt              # 顶层 ESP-IDF 工程
├── sdkconfig.defaults         # 目标 esp32s3、TinyUSB、native USB、控制台走 UART0
├── partitions.csv             # 单 app 分区表
├── idf_component.yml          # 依赖 espressif/esp_tinyusb（Task 2 决策点）
└── main/
    ├── CMakeLists.txt
    ├── app_main.c             # 初始化 + 任务编排
    ├── cardputer_pins.h       # 板级 GPIO 常量（test pattern 是其正确性的预言机）
    ├── display_st7789.c/.h    # esp_lcd 初始化 + display_blit()
    ├── usb_descriptors.c/.h   # device + config 描述符（P0：单 vendor 接口）
    ├── gud_protocol.h         # 从内核 include/drm/gud.h 复制的协议定义
    └── gud_device.c/.h        # GUD 控制请求处理 + bulk OUT 收帧 → display_blit()
```

每个文件单一职责；descriptor/protocol/display 解耦，P1–P5 在此基础上加 UAC/HID 模块、改描述符。

---

## Task 0：ESP-IDF 工程骨架 + 烧录/控制台冒烟

**Files:**
- Create: `firmware/CMakeLists.txt`
- Create: `firmware/sdkconfig.defaults`
- Create: `firmware/partitions.csv`
- Create: `firmware/main/CMakeLists.txt`
- Create: `firmware/main/app_main.c`

- [ ] **Step 1：定义成功判据**

烧录后 `idf.py monitor` 每秒打印一行心跳日志，证明工具链、目标芯片、烧录链路通。

- [ ] **Step 2：写顶层 CMakeLists.txt**

```cmake
cmake_minimum_required(VERSION 3.16)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(cardputer_aio)
```

- [ ] **Step 3：写 sdkconfig.defaults**

```
CONFIG_IDF_TARGET="esp32s3"
CONFIG_ESPTOOLPY_FLASHSIZE_8MB=y
CONFIG_PARTITION_TABLE_CUSTOM=y
CONFIG_PARTITION_TABLE_CUSTOM_FILENAME="partitions.csv"
# P0 阶段控制台仍走 USB-Serial-JTAG；Task 2 起改 UART0
CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG=y
CONFIG_FREERTOS_HZ=1000
```

- [ ] **Step 4：写 partitions.csv**

```
# Name,   Type, SubType, Offset,  Size
nvs,      data, nvs,     0x9000,  0x6000
phy_init, data, phy,     0xf000,  0x1000
factory,  app,  factory, 0x10000, 0x300000
```

- [ ] **Step 5：写 main/CMakeLists.txt**

```cmake
idf_component_register(SRCS "app_main.c"
                       INCLUDE_DIRS ".")
```

- [ ] **Step 6：写 main/app_main.c（心跳）**

```c
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"

static const char *TAG = "aio";

void app_main(void)
{
    int n = 0;
    while (1) {
        ESP_LOGI(TAG, "cardputer-aio alive %d", n++);
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}
```

- [ ] **Step 7：构建并烧录，运行成功判据**

```bash
cd components/packages/cardputer-all-in-one/firmware
get_idf_551 && idf.py set-target esp32s3 && idf.py build
idf.py -p /dev/ttyACM0 flash monitor
```
Expected：monitor 每秒出 `I (xxxx) aio: cardputer-aio alive N`。（端口名以实际为准，可能是 `/dev/ttyACM0` 或 `/dev/ttyUSB0`。）

- [ ] **Step 8：提交**

```bash
git add components/packages/cardputer-all-in-one/firmware
git commit -m "feat(cardputer-fw): ESP-IDF 工程骨架 + 心跳冒烟 (P0 Task0)"
```

---

## Task 1：ST7789 显示 bring-up（无 USB）→ 测试图案

独立验证显示路径，把它和 USB 解耦。

**Files:**
- Create: `firmware/main/cardputer_pins.h`
- Create: `firmware/main/display_st7789.h`
- Create: `firmware/main/display_st7789.c`
- Modify: `firmware/main/app_main.c`
- Modify: `firmware/main/CMakeLists.txt`

- [ ] **Step 1：定义成功判据**

上电后 Cardputer 屏显示**竖直彩条**（红/绿/蓝/白），无错位、无花屏、颜色正确。屏若错位/反色 → 调本任务的 gap/invert/swap 常量；**屏幕正确即证明引脚与面板参数正确**。

- [ ] **Step 2：写 cardputer_pins.h**

> GPIO 值取自 M5 Cardputer 接线（M5GFX 自动检测使用的同一组）。**若 Task1 出不来图案或图案异常，这里是首要排查点**——对照 M5Stack Cardputer 原理图核对。

```c
#pragma once
#define LCD_SPI_HOST   SPI2_HOST
#define PIN_LCD_SCLK   36
#define PIN_LCD_MOSI   35
#define PIN_LCD_DC     34
#define PIN_LCD_CS     37
#define PIN_LCD_RST    33
#define PIN_LCD_BL     38
#define LCD_W          240
#define LCD_H          135
#define LCD_X_OFFSET   40   /* ST7789 240x135 GRAM 偏移，按图案微调 */
#define LCD_Y_OFFSET   52   /* 同上 */
```

- [ ] **Step 3：写 display_st7789.h**

```c
#pragma once
#include "esp_err.h"
#include <stdint.h>

esp_err_t display_init(void);
/* 把 RGB565 像素块 blit 到 (x,y) 起的 w×h 区域；pixels 为大端? 见实现说明 */
void display_blit(int x, int y, int w, int h, const void *pixels);
```

- [ ] **Step 4：写 display_st7789.c**

```c
#include "display_st7789.h"
#include "cardputer_pins.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_vendor.h"
#include "esp_lcd_panel_ops.h"
#include "driver/spi_master.h"
#include "driver/gpio.h"
#include "esp_log.h"

static const char *TAG = "disp";
static esp_lcd_panel_handle_t s_panel;

esp_err_t display_init(void)
{
    gpio_config_t bk = { .mode = GPIO_MODE_OUTPUT,
                         .pin_bit_mask = 1ULL << PIN_LCD_BL };
    gpio_config(&bk);
    gpio_set_level(PIN_LCD_BL, 1);

    spi_bus_config_t buscfg = {
        .sclk_io_num = PIN_LCD_SCLK,
        .mosi_io_num = PIN_LCD_MOSI,
        .miso_io_num = -1, .quadwp_io_num = -1, .quadhd_io_num = -1,
        .max_transfer_sz = LCD_W * LCD_H * 2 + 16,
    };
    ESP_ERROR_CHECK(spi_bus_initialize(LCD_SPI_HOST, &buscfg, SPI_DMA_CH_AUTO));

    esp_lcd_panel_io_handle_t io = NULL;
    esp_lcd_panel_io_spi_config_t io_cfg = {
        .dc_gpio_num = PIN_LCD_DC,
        .cs_gpio_num = PIN_LCD_CS,
        .pclk_hz = 40 * 1000 * 1000,
        .lcd_cmd_bits = 8, .lcd_param_bits = 8,
        .spi_mode = 0, .trans_queue_depth = 10,
    };
    ESP_ERROR_CHECK(esp_lcd_new_panel_io_spi(
        (esp_lcd_spi_bus_handle_t)LCD_SPI_HOST, &io_cfg, &io));

    esp_lcd_panel_dev_config_t pcfg = {
        .reset_gpio_num = PIN_LCD_RST,
        .rgb_ele_order = LCD_RGB_ELEMENT_ORDER_RGB,
        .bits_per_pixel = 16,
    };
    ESP_ERROR_CHECK(esp_lcd_new_panel_st7789(io, &pcfg, &s_panel));
    ESP_ERROR_CHECK(esp_lcd_panel_reset(s_panel));
    ESP_ERROR_CHECK(esp_lcd_panel_init(s_panel));
    ESP_ERROR_CHECK(esp_lcd_panel_invert_color(s_panel, true)); /* ST7789 常需反色 */
    esp_lcd_panel_swap_xy(s_panel, true);
    esp_lcd_panel_mirror(s_panel, false, true);
    esp_lcd_panel_set_gap(s_panel, LCD_X_OFFSET, LCD_Y_OFFSET);
    ESP_ERROR_CHECK(esp_lcd_panel_disp_on_off(s_panel, true));
    ESP_LOGI(TAG, "ST7789 %dx%d ready", LCD_W, LCD_H);
    return ESP_OK;
}

void display_blit(int x, int y, int w, int h, const void *pixels)
{
    esp_lcd_panel_draw_bitmap(s_panel, x, y, x + w, y + h, pixels);
}
```

- [ ] **Step 5：在 app_main.c 画彩条**

```c
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "display_st7789.h"
#include <string.h>

#define LCD_W 240
#define LCD_H 135

static uint16_t fb[LCD_W * LCD_H];

static void fill_bars(void)
{
    const uint16_t bars[4] = {0xF800, 0x07E0, 0x001F, 0xFFFF}; /* R G B W (RGB565) */
    for (int y = 0; y < LCD_H; y++)
        for (int x = 0; x < LCD_W; x++)
            fb[y * LCD_W + x] = bars[(x * 4) / LCD_W];
}

void app_main(void)
{
    ESP_ERROR_CHECK(display_init());
    fill_bars();
    display_blit(0, 0, LCD_W, LCD_H, fb);
    while (1) vTaskDelay(pdMS_TO_TICKS(1000));
}
```

- [ ] **Step 6：更新 main/CMakeLists.txt**

```cmake
idf_component_register(SRCS "app_main.c" "display_st7789.c"
                       INCLUDE_DIRS ".")
```

- [ ] **Step 7：构建烧录，运行成功判据**

```bash
get_idf_551 && idf.py build && idf.py -p /dev/ttyACM0 flash monitor
```
Expected：屏幕出红/绿/蓝/白竖直彩条。**若错位**：调 `LCD_X_OFFSET/LCD_Y_OFFSET`；**若反色**：翻 `invert_color`；**若镜像/旋转不对**：调 `swap_xy/mirror`。

- [ ] **Step 8：提交**

```bash
git add components/packages/cardputer-all-in-one/firmware
git commit -m "feat(cardputer-fw): ST7789 显示 bring-up + 彩条 (P0 Task1)"
```

---

## Task 2：TinyUSB vendor 设备枚举（GUD VID/PID）

**Files:**
- Create: `firmware/idf_component.yml`
- Create: `firmware/main/usb_descriptors.h`
- Create: `firmware/main/usb_descriptors.c`
- Modify: `firmware/sdkconfig.defaults`（控制台改 UART0 + 开 vendor class）
- Modify: `firmware/main/app_main.c`
- Modify: `firmware/main/CMakeLists.txt`

- [ ] **Step 1：定义成功判据**

把 Cardputer 插到开发机 USB，`lsusb` 出现 `16d0:10a9`；`sudo dmesg | tail` 显示 `gud` 尝试 probe 该设备（probe 会因协议未实现而失败/报错——**这正是"VID/PID 正确、已被 gud 认领"的信号**，Task3 修复 probe）。

- [ ] **Step 2：决策并写 idf_component.yml**

```yaml
dependencies:
  espressif/esp_tinyusb: "^1.4.0"
```
> **决策点**：`esp_tinyusb` 若未暴露 vendor class 自定义控制回调（`tud_vendor_control_xfer_cb`），则改为直接依赖上游 tinyusb 并自带 `tusb_config.h`。判据：Step 7 能收到 vendor 控制请求日志。先按 `esp_tinyusb` 尝试。

- [ ] **Step 3：sdkconfig.defaults 改控制台 + 开 vendor**

把 `CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG=y` 改为：
```
CONFIG_ESP_CONSOLE_UART_DEFAULT=y
CONFIG_ESP_CONSOLE_UART_NUM=0
CONFIG_TINYUSB_VENDOR_ENABLED=y
CONFIG_TINYUSB_VENDOR_RX_BUFSIZE=4096
CONFIG_TINYUSB_VENDOR_TX_BUFSIZE=4096
```
> 此后固件日志走 UART0（G43/G44）。USB-C 用于 OTG，烧录改按住 **G0(BOOT)** 上电进下载模式。

- [ ] **Step 4：写 usb_descriptors.h**

```c
#pragma once
#include "tusb.h"

#define GUD_VID  0x16D0
#define GUD_PID  0x10A9

enum { ITF_NUM_VENDOR = 0, ITF_NUM_TOTAL };
enum { EPNUM_VENDOR_OUT = 0x01, EPNUM_VENDOR_IN = 0x81 };
```

- [ ] **Step 5：写 usb_descriptors.c**

```c
#include "usb_descriptors.h"

tusb_desc_device_t const desc_device = {
    .bLength = sizeof(tusb_desc_device_t),
    .bDescriptorType = TUSB_DESC_DEVICE,
    .bcdUSB = 0x0200,
    .bDeviceClass = 0x00, .bDeviceSubClass = 0x00, .bDeviceProtocol = 0x00,
    .bMaxPacketSize0 = CFG_TUD_ENDPOINT0_SIZE,
    .idVendor = GUD_VID, .idProduct = GUD_PID, .bcdDevice = 0x0100,
    .iManufacturer = 0x01, .iProduct = 0x02, .iSerialNumber = 0x03,
    .bNumConfigurations = 0x01,
};
uint8_t const *tud_descriptor_device_cb(void) { return (uint8_t const *)&desc_device; }

#define CONFIG_TOTAL_LEN (TUD_CONFIG_DESC_LEN + TUD_VENDOR_DESC_LEN)

uint8_t const desc_configuration[] = {
    TUD_CONFIG_DESCRIPTOR(1, ITF_NUM_TOTAL, 0, CONFIG_TOTAL_LEN, 0x00, 100),
    /* vendor 接口必须 bInterfaceClass=0xFF；TUD_VENDOR_DESCRIPTOR 即如此 */
    TUD_VENDOR_DESCRIPTOR(ITF_NUM_VENDOR, 0, EPNUM_VENDOR_OUT, EPNUM_VENDOR_IN, 64),
};
uint8_t const *tud_descriptor_configuration_cb(uint8_t index) {
    (void)index; return desc_configuration;
}

char const *string_desc_arr[] = {
    (const char[]){0x09, 0x04}, "flange", "Cardputer GUD Display", "AIO-0001",
};
/* 标准 string descriptor 回调（按 TinyUSB 例程模板实现，UTF-16 转换） */
static uint16_t _desc_str[32];
uint16_t const *tud_descriptor_string_cb(uint8_t index, uint16_t langid) {
    (void)langid; uint8_t chr_count;
    if (index == 0) { _desc_str[1] = 0x0409; chr_count = 1; }
    else {
        if (index >= sizeof(string_desc_arr)/sizeof(string_desc_arr[0])) return NULL;
        const char *str = string_desc_arr[index];
        chr_count = strlen(str); if (chr_count > 31) chr_count = 31;
        for (uint8_t i = 0; i < chr_count; i++) _desc_str[1+i] = str[i];
    }
    _desc_str[0] = (uint16_t)((TUSB_DESC_STRING << 8) | (2*chr_count + 2));
    return _desc_str;
}
```
> 顶部需 `#include <string.h>`。

- [ ] **Step 6：app_main.c 安装 TinyUSB**

在显示初始化后加：
```c
#include "tinyusb.h"
...
    const tinyusb_config_t tusb_cfg = {
        .device_descriptor = NULL,        /* 用我们的 *_cb 回调 */
        .configuration_descriptor = NULL,
        .string_descriptor = NULL,
    };
    ESP_ERROR_CHECK(tinyusb_driver_install(&tusb_cfg));
    ESP_LOGI("aio", "tinyusb installed (16d0:10a9)");
```
> 若 `esp_tinyusb` 要求显式传描述符，则把上面三个字段指向 `desc_device` / `desc_configuration` / `string_desc_arr`。

- [ ] **Step 7：构建烧录，运行成功判据**

```bash
get_idf_551 && idf.py build
# 按住 G0 上电进下载模式后：
idf.py -p /dev/ttyACM0 flash
# 插上设备，host 侧：
lsusb | grep 16d0:10a9
sudo dmesg | tail -20
```
Expected：`lsusb` 出 `16d0:10a9`；`dmesg` 见 `usb ... idVendor=16d0, idProduct=10a9` 及 `gud` probe 尝试（此刻 probe 失败属预期）。

- [ ] **Step 8：提交**

```bash
git add components/packages/cardputer-all-in-one/firmware
git commit -m "feat(cardputer-fw): TinyUSB vendor 设备枚举(16d0:10a9) (P0 Task2)"
```

---

## Task 3：实现 GUD 控制协议 → gud probe 成功，modetest 见 connector+模式

**Files:**
- Create: `firmware/main/gud_protocol.h`（复制内核协议定义）
- Create: `firmware/main/gud_device.h`
- Create: `firmware/main/gud_device.c`
- Modify: `firmware/main/app_main.c`
- Modify: `firmware/main/CMakeLists.txt`

- [ ] **Step 1：定义成功判据**

host 侧 `gud` probe 成功，`/dev/dri/cardN` 出现，`modetest -M gud` 列出一个 connector 和 `240x135` 模式。

- [ ] **Step 2：host 装 modetest**

```bash
sudo apt-get install -y libdrm-tests || sudo apt-get install -y libdrm-common
which modetest && modetest -M gud   # 现在应报找不到设备（设备还没答协议）
```

- [ ] **Step 3：复制 GUD 协议头**

从内核源 `include/drm/gud.h`（Dual MIT/GPL）复制到 `firmware/main/gud_protocol.h`，保留许可证头。来源任一：
- 本机内核源（若装了 linux-source 对应版本）；或
- `https://github.com/notro/gud`（仓库含协议定义 + 设备参考实现）。

关键定义（实现 Task3/4 会用到，**以复制来的头为准**）：请求码 `GUD_REQ_GET_STATUS / GET_DESCRIPTOR / GET_FORMATS / GET_PROPERTIES / GET_CONNECTORS / GET_CONNECTOR_PROPERTIES / GET_CONNECTOR_STATUS / GET_CONNECTOR_MODES / SET_BUFFER / SET_STATE_CHECK / SET_STATE_COMMIT / SET_CONTROLLER_ENABLE / SET_DISPLAY_ENABLE`；魔数 `GUD_DISPLAY_MAGIC`；结构体 `gud_display_descriptor_req / gud_property_req / gud_connector_descriptor_req / gud_display_mode_req / gud_set_buffer_req`；像素格式 `GUD_PIXEL_FORMAT_RGB565`。

- [ ] **Step 4：写 gud_device.h**

```c
#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "tusb.h"

/* TinyUSB vendor 控制请求回调里转发到这里。返回 true 表示已处理。 */
bool gud_handle_control(uint8_t rhport, uint8_t stage,
                        tusb_control_request_t const *req);
void gud_init(void);
```

- [ ] **Step 5：写 gud_device.c（控制协议最小子集）**

按复制来的 `gud_protocol.h` 实现以下控制请求的应答（device→host 为主）。结构与判据：

```c
#include "gud_device.h"
#include "gud_protocol.h"
#include "display_st7789.h"
#include "esp_log.h"
#include <string.h>

static const char *TAG = "gud";

/* 单 connector / 单模式 240x135 / RGB565，硬编码即可（P0） */

static bool send_descriptor(uint8_t rhport, tusb_control_request_t const *req) {
    struct gud_display_descriptor_req d = {0};
    d.magic = GUD_DISPLAY_MAGIC;
    d.version = 1;
    d.flags = 0;                 /* P0 不声明压缩 */
    d.max_buffer_size = 0;       /* 0 = 用 mode 尺寸 */
    d.min_width = d.max_width = 240;
    d.min_height = d.max_height = 135;
    return tud_control_xfer(rhport, req, &d, sizeof(d));
}
/* 类似实现：
   GET_FORMATS  → 返回 {GUD_PIXEL_FORMAT_RGB565}
   GET_PROPERTIES / GET_CONNECTOR_PROPERTIES → 返回 0 条（count=0）
   GET_CONNECTORS → 1 个 connector descriptor（类型 unknown/SPI panel）
   GET_CONNECTOR_STATUS → connected
   GET_CONNECTOR_MODES → 1 个 gud_display_mode_req（240x135，clock/htotal 等填合理值）
   SET_CONTROLLER_ENABLE / SET_DISPLAY_ENABLE → 收 1 字节，ACK
   SET_STATE_CHECK / SET_STATE_COMMIT → 收 state 块，ACK
*/

bool gud_handle_control(uint8_t rhport, uint8_t stage,
                        tusb_control_request_t const *req) {
    if (stage != CONTROL_STAGE_SETUP) return true;  /* 数据/状态阶段交给 TinyUSB */
    switch (req->bRequest) {
    case GUD_REQ_GET_DESCRIPTOR:        return send_descriptor(rhport, req);
    /* ... 其余 case 同上注释 ... */
    default:
        ESP_LOGW(TAG, "unhandled gud req 0x%02x wValue=%u wIndex=%u len=%u",
                 req->bRequest, req->wValue, req->wIndex, req->wLength);
        return false;
    }
}

void gud_init(void) { ESP_LOGI(TAG, "gud device ready 240x135 rgb565"); }
```
> **实现提示**：用 Task2 的 UART0 日志看 host 实际发来的请求序列（probe 时按固定顺序发），照序补齐 case。`notro/gud` 的设备参考实现是逐请求对照的最佳样板。

- [ ] **Step 6：把 vendor 控制回调接到 gud（usb_descriptors.c 或新文件）**

```c
#include "gud_device.h"
/* TinyUSB 在收到 bmRequestType.type == VENDOR 的控制请求时调用此弱回调 */
bool tud_vendor_control_xfer_cb(uint8_t rhport, uint8_t stage,
                                tusb_control_request_t const *req) {
    return gud_handle_control(rhport, stage, req);
}
```

- [ ] **Step 7：app_main.c 调 gud_init() + main/CMakeLists.txt 加 gud_device.c**

```cmake
idf_component_register(SRCS "app_main.c" "display_st7789.c"
                            "usb_descriptors.c" "gud_device.c"
                       INCLUDE_DIRS ".")
```

- [ ] **Step 8：构建烧录，运行成功判据**

```bash
get_idf_551 && idf.py build && idf.py -p /dev/ttyACM0 flash   # 按需 G0
# host：
sudo dmesg | tail -20            # 期望见 gud probe 成功、新建 drm card
ls /dev/dri/                     # 期望多出一个 cardN
modetest -M gud                  # 期望列出 1 connector + 240x135 模式
```
Expected：`dmesg` 见 `[drm] ... gud` 成功；`modetest -M gud` 列出 connector 与 `240x135`。

- [ ] **Step 9：提交**

```bash
git add components/packages/cardputer-all-in-one/firmware
git commit -m "feat(cardputer-fw): GUD 控制协议最小子集, gud 绑定出 card (P0 Task3)"
```

---

## Task 4：GUD SET_BUFFER + bulk OUT 收帧 → blit 上屏

**Files:**
- Modify: `firmware/main/gud_device.c`（处理 SET_BUFFER + bulk OUT 数据）
- Modify: `firmware/main/app_main.c`（建显示任务/帧缓冲）

- [ ] **Step 1：定义成功判据**

`modetest -M gud -s <connector_id>:240x135` 后，Cardputer 屏显示 modetest 的测试图（彩条/SMPTE）。`kmscube`（可选）显示动画。

- [ ] **Step 2：实现 SET_BUFFER 控制请求**

在 `gud_device.c` 加 `GUD_REQ_SET_BUFFER` case：解析 `gud_set_buffer_req`（含 x/y/width/height、length、compression、compressed_length），**P0 只接受 compression==0（未压缩 RGB565）**，记下接下来 bulk OUT 要收的字节数与目标矩形。

- [ ] **Step 3：实现 bulk OUT 收帧并 blit**

```c
/* TinyUSB vendor bulk OUT 数据到达回调 */
void tud_vendor_rx_cb(uint8_t itf, uint8_t const *buffer, uint16_t bufsize) {
    /* 累积到当前 SET_BUFFER 描述的矩形缓冲；收满后： */
    /* display_blit(rect.x, rect.y, rect.w, rect.h, rect_pixels); */
}
```
> 用一个 static 帧缓冲（240×135×2 = 63 KB，放内部 SRAM）。注意字节序：GUD RGB565 与 `esp_lcd` 期望的端序若不一致需 byteswap（先不 swap，颜色错了再加）。

- [ ] **Step 4：构建烧录，运行成功判据**

```bash
get_idf_551 && idf.py build && idf.py -p /dev/ttyACM0 flash   # 按需 G0
# host（connector id 从 modetest -M gud 读）：
modetest -M gud -s <connector_id>:240x135
```
Expected：Cardputer 屏出 modetest 测试图。颜色不对 → byteswap；位置不对 → 核对 blit 矩形与 set_gap。

- [ ] **Step 5：（可选）kmscube 动画**

```bash
sudo apt-get install -y kmscube && kmscube -D /dev/dri/cardN
```
Expected：屏上转动的立方体（帧率低属正常，P0 未压缩/未脏矩形）。

- [ ] **Step 6：提交**

```bash
git add components/packages/cardputer-all-in-one/firmware
git commit -m "feat(cardputer-fw): GUD SET_BUFFER+bulk 收帧上屏, 一线出画面 (P0 Task4)"
```

---

## Task 5：P0 收尾 — README + 里程碑

**Files:**
- Create: `firmware/README.md`
- Create: `components/packages/cardputer-all-in-one/README.md`

- [ ] **Step 1：写 firmware/README.md**

内容：构建/烧录命令（`get_idf_551 && idf.py ...`、G0 下载模式）、日志走 UART0(G43/G44 @115200) 说明、host 验证命令（lsusb/dmesg/modetest）、当前能力（P0：未压缩 GUD 显示）、已知限制（无压缩/无脏矩形/无音频/无键盘）。

- [ ] **Step 2：写组件 README.md**

内容：组件目标、两侧分工（firmware 容器外构建 / Linux 侧 P4 再做）、指向设计 spec 与各阶段计划。

- [ ] **Step 3：提交 + 打里程碑标签**

```bash
git add components/packages/cardputer-all-in-one
git commit -m "docs(cardputer): P0 README + 验证说明"
git tag cardputer-p0-gud-display
```

---

## P0 完成判据（DoD）

- [ ] 一根 USB 线接 Cardputer 到开发机，`modetest -M gud -s <conn>:240x135` 能把画面送上 Cardputer 屏。
- [ ] `/dev/dri/cardN` 由 mainline `gud` 自动创建，host 侧零自定义驱动。
- [ ] 全部步骤命令与期望输出可复现，README 记录在案。

---

## 自检（against spec）

- **§2/§3 GUD 全 mainline、零自定义驱动**：Task2–4 用官方 16d0:10a9 + mainline gud，host 零驱动 ✓
- **§3.1 vendor 接口 class=0xFF**：Task2 `TUD_VENDOR_DESCRIPTOR` ✓
- **§4 显示模块 esp_lcd + 脏矩形 blit**：Task1 esp_lcd；脏矩形在 P3（P0 用 SET_BUFFER 全/分块未压缩）✓（P0 范围内）
- **§7 风险3 USB-Serial-JTAG 冲突 / log 走 UART0**：Task2 Step3 显式切 UART0 ✓
- **§7 风险4 无 PSRAM / 63KB 帧缓冲入 SRAM**：Task4 Step3 内部 SRAM 帧缓冲 ✓
- **音频/HID/LZ4/Linux 组件**：明确不在 P0，列入后续计划 ✓（范围决策）
- 占位符扫描：GUD 协议常量以「复制内核头」方式定义（非杜撰），其余代码完整 ✓

---

## 后续计划（各自独立成文，P0 落地后再写）

| 阶段 | 计划文件（待建）| 产出 | 关键依赖于 P0 的实测 |
|------|----------------|------|---------------------|
| P1 | `...-p1-uac-audio.md` | UAC1 mono16k 扬声器(下行)+麦(上行)，复合进描述符 | 复合描述符排布、esp_tinyusb 是否支持 audio+vendor 共存、扬声/麦 GPIO |
| P2 | `...-p2-hid-keyboard.md` | 矩阵键盘 → USB HID，复合进描述符 | 键盘扫描引脚、Fn 层映射 |
| P3 | `...-p3-lz4-damage.md` | GUD 声明 LZ4 + 脏矩形增量刷新，实测帧率/延迟 | P0 实测带宽/帧率基线 |
| P4 | `...-p4-flange-component.md` | Linux 侧 flange 组件（kernel config fragment + udev + 示例单元），`flange build` 出镜像 | 目标板内核 config 现状 |
| P5（可选）| `...-p5-flash-thinclient.md` | `flange flash` 封装 esptool + 瘦终端体验整合 | flash 子命令架构 |
