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
