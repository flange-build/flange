#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "tinyusb.h"
#include "tinyusb_default_config.h"
#include "display_dsi.h"
#include "usb_descriptors.h"
#include "gud_device.h"
#include "board_power.h"
#include "tab5_pins.h"

static const char *TAG = "tab5_aio";

void app_main(void)
{
    ESP_ERROR_CHECK(board_power_init());

    /* 临时：扫描内部 I2C，用于确定本机面板/触摸控制器型号。
     * 见 0x55 ⇒ ST7123；见 0x14 ⇒ GT911(面板为 ILI9881C)。
     * TODO(Task2): 型号确定后删除本段。 */
    for (uint8_t a = 0x08; a < 0x78; a++) {
        if (i2c_master_probe(board_i2c_bus(), a, 50) == ESP_OK)
            ESP_LOGI("i2cscan", "found 0x%02x", a);
    }

    ESP_ERROR_CHECK(display_init());

    /* 面板自检：4 条竖直色条（面板竖屏坐标系，x 是短边 720） */
    uint16_t *fb = display_frame_buffer();
    const uint16_t bars[4] = {0xF800, 0x07E0, 0x001F, 0xFFFF}; /* R G B W (RGB565) */
    for (int y = 0; y < PANEL_H; y++)
        for (int x = 0; x < PANEL_W; x++)
            fb[y * PANEL_W + x] = bars[(x * 4) / PANEL_W];

    /* GUD 控制协议状态机初始化（须在 TinyUSB 安装前，回调可能立即触发） */
    ESP_ERROR_CHECK(gud_device_init());

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
