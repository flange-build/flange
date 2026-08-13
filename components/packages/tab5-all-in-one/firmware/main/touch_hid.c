/*
 * M5Stack Tab5 电容触摸（GT911）→ 坐标日志。
 *
 * GT911 与 IO 扩展/codec/IMU 同挂**内部 I2C**（G31/G32），故直接复用
 * board_i2c_bus() 的总线句柄，不像键盘那样自建总线。
 * 触摸电源使能在 PI4IOE5V6408-1(0x43) 的 PIN5 上，board_power_init() 已拉高。
 */
#include "touch_hid.h"
#include "touch_map.h"
#include "tab5_pins.h"
#include "board_power.h"
#include "esp_lcd_touch_gt911.h"
#include "esp_lcd_panel_io.h"
#include "esp_check.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "touch";

/* 轮询周期。触摸不像键盘那样怕丢事件（坐标是状态而非边沿），20ms
 * 对指针跟随已经足够跟手，无需中断驱动。 */
#define TOUCH_POLL_MS 20

/* esp_lcd_touch 一次最多返回 CONFIG_ESP_LCD_TOUCH_MAX_POINTS 个点；
 * 本阶段只看第一个点，但缓冲要按上限开 —— esp_lcd_touch_get_data() 会
 * memset 满 max_point_cnt 个元素，传小了就是越界写。 */
#define TOUCH_POINTS_MAX CONFIG_ESP_LCD_TOUCH_MAX_POINTS

static esp_lcd_touch_handle_t s_tp;

static void touch_task(void *arg)
{
    (void)arg;
    uint8_t last_points = 0;

    while (1) {
        vTaskDelay(pdMS_TO_TICKS(TOUCH_POLL_MS));

        if (esp_lcd_touch_read_data(s_tp) != ESP_OK)
            continue;

        /* 用 esp_lcd_touch_get_data() 而非 esp_lcd_touch_get_coordinates()：
         * 后者在 esp_lcd_touch 1.2.x 已标 deprecated（2.0.0 移除），编译告警。 */
        esp_lcd_touch_point_data_t pts[TOUCH_POINTS_MAX];
        uint8_t points = 0;
        if (esp_lcd_touch_get_data(s_tp, pts, &points, TOUCH_POINTS_MAX) != ESP_OK)
            continue;

        if (points > 0) {
            /* 标定期原始值与变换后都要看：原始值判 GT911 的出数朝向，
             * 变换后判它与 host 画面是否对得上。 */
            uint16_t gud_x = 0, gud_y = 0;
            touch_map_panel_to_gud(pts[0].x, pts[0].y, &gud_x, &gud_y);
            ESP_LOGI(TAG, "raw(%u,%u) → gud(%u,%u) n=%u",
                     (unsigned)pts[0].x, (unsigned)pts[0].y,
                     (unsigned)gud_x, (unsigned)gud_y, (unsigned)points);
        } else if (last_points > 0) {
            /* 抬起也打一条：标定时要能分清「没动」与「松手了」 */
            ESP_LOGI(TAG, "release");
        }
        last_points = points;
    }
}

esp_err_t touch_start(void)
{
    /*
     * ⚠️ GT911 的**默认**地址是 0x5D，0x14 是备用地址 —— Tab5 用的正是 0x14。
     * ESP_LCD_TOUCH_IO_I2C_GT911_CONFIG() 宏填的是 0x5D，且组件只校验传入值
     * 合法、不会自动探测（esp_lcd_touch_gt911.c 的地址选择流程还要求有 rst
     * 引脚，Tab5 没有，那段直接被跳过）。不显式改成 BACKUP 就一定探不到。
     */
    esp_lcd_panel_io_i2c_config_t io_cfg = ESP_LCD_TOUCH_IO_I2C_GT911_CONFIG();
    io_cfg.dev_addr = ESP_LCD_TOUCH_IO_I2C_GT911_ADDRESS_BACKUP;

    esp_lcd_panel_io_handle_t io = NULL;
    ESP_RETURN_ON_ERROR(esp_lcd_new_panel_io_i2c(board_i2c_bus(), &io_cfg, &io),
                        TAG, "touch panel io");

    esp_lcd_touch_config_t tp_cfg = {
        .x_max = PANEL_W,
        .y_max = PANEL_H,
        .rst_gpio_num = GPIO_NUM_NC,        /* Tab5 触摸没有独立 reset 脚 */
        .int_gpio_num = PIN_TOUCH_INT,
        .levels = {
            .reset = 0,
            .interrupt = 0,
        },
        /* 三个方向 flag 全 0：先按 GT911 原始出数打日志，方向标定在下一步做。 */
        .flags = {
            .swap_xy = 0,
            .mirror_x = 0,
            .mirror_y = 0,
        },
    };
    ESP_RETURN_ON_ERROR(esp_lcd_touch_new_i2c_gt911(io, &tp_cfg, &s_tp), TAG,
                        "gt911 未应答(0x%02x)，检查内部 I2C 与触摸电源",
                        ESP_LCD_TOUCH_IO_I2C_GT911_ADDRESS_BACKUP);

    ESP_LOGI(TAG, "gt911 ready (addr=0x%02x, int=G%d)",
             ESP_LCD_TOUCH_IO_I2C_GT911_ADDRESS_BACKUP, PIN_TOUCH_INT);

    xTaskCreate(touch_task, "touch", 4096, NULL, 5, NULL);
    return ESP_OK;
}
