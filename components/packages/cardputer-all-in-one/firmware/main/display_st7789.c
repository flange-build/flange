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

/*
 * M5Cardputer ST7789 电源/VCOM/gamma 校准序列(值取自 LovyanGFX Panel_ST7789，
 * 即 M5GFX 实际使用的序列)。esp_lcd 通用 init 只发 SLPOUT/MADCTL/COLMOD/RAMCTRL，
 * 未加载电源与 gamma 曲线，面板跑在上电默认 gamma 上，导致灰阶中低亮度偏绿偏暖。
 * 此处仅补电源+VCOM+gamma；不重发 MADCTL/COLMOD/RAMCTRL/SLPOUT/DISPON(由 esp_lcd
 * 负责)，尤其不动字节序，以保持已端到端验证的通道映射不变。
 */
typedef struct { uint8_t cmd; uint8_t len; uint8_t data[14]; } st7789_init_cmd_t;
static const st7789_init_cmd_t k_init_seq[] = {
    {0xB7, 1,  {0x35}},                 /* GCTRL    */
    {0xBB, 1,  {0x28}},                 /* VCOMS    */
    {0xC0, 1,  {0x0C}},                 /* LCMCTRL  */
    {0xC2, 2,  {0x01, 0xFF}},           /* VDVVRHEN */
    {0xC3, 1,  {0x10}},                 /* VRHS     */
    {0xC4, 1,  {0x20}},                 /* VDVSET   */
    {0xD0, 2,  {0xA4, 0xA1}},           /* PWCTRL1  */
    {0xE0, 14, {0xD0,0x00,0x02,0x07,0x0A,0x28,0x32,0x44,0x42,0x06,0x0E,0x12,0x14,0x17}}, /* PVGAMCTRL */
    {0xE1, 14, {0xD0,0x00,0x02,0x07,0x0A,0x28,0x31,0x54,0x47,0x0E,0x1C,0x17,0x1B,0x1E}}, /* NVGAMCTRL */
};

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
        .rgb_ele_order = LCD_RGB_ELEMENT_ORDER_BGR, /* 实测红蓝互换，用 BGR 顺序面板级交换 */
        .bits_per_pixel = 16,
    };
    ESP_ERROR_CHECK(esp_lcd_new_panel_st7789(io, &pcfg, &s_panel));
    ESP_ERROR_CHECK(esp_lcd_panel_reset(s_panel));
    ESP_ERROR_CHECK(esp_lcd_panel_init(s_panel));
    /* 补发 M5Cardputer 电源/VCOM/gamma 校准序列(esp_lcd init 未覆盖) */
    for (size_t i = 0; i < sizeof(k_init_seq) / sizeof(k_init_seq[0]); i++) {
        ESP_ERROR_CHECK(esp_lcd_panel_io_tx_param(
            io, k_init_seq[i].cmd, k_init_seq[i].data, k_init_seq[i].len));
    }
    ESP_ERROR_CHECK(esp_lcd_panel_invert_color(s_panel, true)); /* ST7789 实测需反色 */
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
