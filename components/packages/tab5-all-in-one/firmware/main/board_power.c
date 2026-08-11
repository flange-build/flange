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
