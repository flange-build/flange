#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "display_st7789.h"
#include "tinyusb.h"
#include "usb_descriptors.h"
#include "gud_device.h"
#include "hid_keyboard.h"
#include <string.h>

/* TODO(GUD): Task 4 引入真实帧时评估是否需移至 PSRAM */
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

    /* GUD 控制协议状态机初始化（须在 TinyUSB 安装前，回调可能立即触发） */
    gud_device_init();

    /* 安装 TinyUSB：vendor 类设备 16d0:10a9，供 mainline gud 驱动绑定。
     * 描述符经 tinyusb_config_t 注入；vendor EP0 控制回调
     * tud_vendor_control_xfer_cb 由 gud_device.c 提供。 */
    const tinyusb_config_t tusb_cfg = {
        .device_descriptor = &aio_desc_device,
        .configuration_descriptor = aio_desc_configuration,
        .string_descriptor = aio_string_desc_arr,
        .string_descriptor_count = aio_string_desc_count,
        .external_phy = false,
    };
    ESP_ERROR_CHECK(tinyusb_driver_install(&tusb_cfg));
    ESP_LOGI("aio", "tinyusb installed (16d0:10a9)");

    /* HID 键盘：TinyUSB 安装后启动测试上报任务 */
    hid_keyboard_start();

    while (1) vTaskDelay(pdMS_TO_TICKS(1000));
}
