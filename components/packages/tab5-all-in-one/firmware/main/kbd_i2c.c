/*
 * M5Stack Tab5 Keyboard（I2C 从机 0x6D）→ USB HID 键盘。
 *
 * 键盘挂在与内部 I2C（G31/G32）物理分离的另一条总线（G0/G1）上，故本文件
 * 自己持有一条 i2c_master_bus，不复用 board_power 的那条。
 *
 * 用固件的 Normal 模式（寄存器 0x10 写 0）读行列事件，自建按下集合状态机；
 * 不用键盘自带的 HID 模式 —— 它的修饰键不进队列、且一次只能表达一个键。
 */
#include "kbd_i2c.h"
#include "tab5_pins.h"
#include "driver/i2c_master.h"
#include "esp_check.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "kbd";

/* 寄存器地址取自官方固件 user_i2c_reg.h。注意 0xFE/0xFF 是绝对地址——
 * 协议图最后一行标的 0xF0 是块基址，Version/Address 在该行 E/F 列。
 * 0xFD 是固件升级入口，误写会变砖，本文件永不触碰。 */
#define REG_INTR_CONFIG    0x00
#define REG_INTR_STATUS    0x01
#define REG_EVENT_NUM      0x02
#define REG_KEYBOARD_MODE  0x10
#define REG_KEY_EVENT      0x20
#define REG_FW_VERSION     0xFE

#define KBD_MODE_NORMAL    0

/* Normal 模式事件：bit7 按下(1)/释放(0)，bit[6:4] 行，bit[3:0] 列；队列空读回 0xFF */
#define KEY_EVENT_EMPTY    0xFF

static i2c_master_bus_handle_t s_bus;
static i2c_master_dev_handle_t s_dev;

static esp_err_t kbd_read_reg(uint8_t reg, uint8_t *out, size_t len)
{
    return i2c_master_transmit_receive(s_dev, &reg, 1, out, len, 100);
}

static esp_err_t kbd_write_reg(uint8_t reg, uint8_t val)
{
    const uint8_t buf[2] = { reg, val };
    return i2c_master_transmit(s_dev, buf, sizeof(buf), 100);
}

static void kbd_task(void *arg)
{
    (void)arg;
    while (1) {
        uint8_t n = 0;
        if (kbd_read_reg(REG_EVENT_NUM, &n, 1) == ESP_OK && n > 0) {
            for (uint8_t i = 0; i < n; i++) {
                uint8_t ev = KEY_EVENT_EMPTY;
                if (kbd_read_reg(REG_KEY_EVENT, &ev, 1) != ESP_OK || ev == KEY_EVENT_EMPTY)
                    break;
                ESP_LOGI(TAG, "raw %s row=%u col=%u",
                         (ev & 0x80) ? "press" : "release",
                         (unsigned)((ev >> 4) & 0x07), (unsigned)(ev & 0x0F));
            }
        }
        vTaskDelay(pdMS_TO_TICKS(15));
    }
}

esp_err_t kbd_start(void)
{
    i2c_master_bus_config_t bus_cfg = {
        .i2c_port = I2C_NUM_1,          /* I2C_NUM_0 已被 board_power 的内部总线占用 */
        .sda_io_num = PIN_KBD_SDA,
        .scl_io_num = PIN_KBD_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    ESP_RETURN_ON_ERROR(i2c_new_master_bus(&bus_cfg, &s_bus), TAG, "kbd i2c bus");

    ESP_RETURN_ON_ERROR(i2c_master_probe(s_bus, KBD_I2C_ADDR, 100), TAG,
                        "键盘未应答(0x%02x)，检查排线与 G0/G1", KBD_I2C_ADDR);

    i2c_device_config_t dev_cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = KBD_I2C_ADDR,
        .scl_speed_hz = 100000,
    };
    ESP_RETURN_ON_ERROR(i2c_master_bus_add_device(s_bus, &dev_cfg, &s_dev), TAG, "kbd i2c dev");

    uint8_t fw = 0;
    ESP_RETURN_ON_ERROR(kbd_read_reg(REG_FW_VERSION, &fw, 1), TAG, "读固件版本失败");
    ESP_RETURN_ON_ERROR(kbd_write_reg(REG_KEYBOARD_MODE, KBD_MODE_NORMAL), TAG, "设 Normal 模式失败");

    ESP_LOGI(TAG, "fw=0x%02x addr=0x%02x mode=normal", fw, KBD_I2C_ADDR);
    xTaskCreate(kbd_task, "kbd", 4096, NULL, 5, NULL);
    return ESP_OK;
}
