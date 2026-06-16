#include "display_st7789.h"
#include "cardputer_pins.h"
#include "esp_lcd_panel_io.h"
#include <assert.h>
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
    ESP_ERROR_CHECK(gpio_config(&bk));
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
    ESP_ERROR_CHECK(esp_lcd_panel_invert_color(s_panel, false)); /* Cardputer 面板实测无需反色（GUD 真机图案验证） */
    ESP_ERROR_CHECK(esp_lcd_panel_swap_xy(s_panel, true));
    ESP_ERROR_CHECK(esp_lcd_panel_mirror(s_panel, true, false)); /* 实测需 180° */
    esp_lcd_panel_set_gap(s_panel, LCD_X_OFFSET, LCD_Y_OFFSET);
    ESP_ERROR_CHECK(esp_lcd_panel_disp_on_off(s_panel, true));
    ESP_LOGI(TAG, "ST7789 %dx%d ready", LCD_W, LCD_H);
    return ESP_OK;
}

void display_blit(int x, int y, int w, int h, const void *pixels)
{
    assert(s_panel);
    esp_lcd_panel_draw_bitmap(s_panel, x, y, x + w, y + h, pixels);
}
