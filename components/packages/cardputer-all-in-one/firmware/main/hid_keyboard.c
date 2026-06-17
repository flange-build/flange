#include "hid_keyboard.h"
#include "cardputer_kbd_map.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gpio.h"
#include "esp_rom_sys.h"
#include "esp_log.h"
#include <string.h>
#include <stdio.h>

static const char *TAG = "hid_kbd";

static void kbd_gpio_init(void)
{
    uint64_t out_mask = 0;
    for (int i = 0; i < KBD_COL_PIN_COUNT; i++) {
        gpio_reset_pin(KBD_COL_PINS[i]); /* 清除可能的复用功能(如 strapping/JTAG) */
        out_mask |= 1ULL << KBD_COL_PINS[i];
    }
    gpio_config_t out_cfg = {
        .mode = GPIO_MODE_OUTPUT,
        .pin_bit_mask = out_mask,
    };
    ESP_ERROR_CHECK(gpio_config(&out_cfg));

    uint64_t in_mask = 0;
    for (int j = 0; j < KBD_ROW_PIN_COUNT; j++) {
        gpio_reset_pin(KBD_ROW_PINS[j]);
        in_mask |= 1ULL << KBD_ROW_PINS[j];
    }
    gpio_config_t in_cfg = {
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE, /* 行常态拉高，按下经选中列拉低 */
        .pin_bit_mask = in_mask,
    };
    ESP_ERROR_CHECK(gpio_config(&in_cfg));
}

/* 把 3 位列选值写到 74HC138 地址线 A0/A1/A2（KBD_COL_PINS[0..2]）。
 * 74HC138 据此把选中列拉低，其余列为高。 */
static void kbd_set_col(int sel)
{
    gpio_set_level(KBD_COL_PINS[0], (sel >> 0) & 1);
    gpio_set_level(KBD_COL_PINS[1], (sel >> 1) & 1);
    gpio_set_level(KBD_COL_PINS[2], (sel >> 2) & 1);
}

/* 一次原始扫描 → 按下键位列表(坐标系同 M5 库)，返回数量。
 * 坐标：x = (i>3)?x_1:x_2；y = 3 - (i%4)（与 M5 库 update() 的 Y 取反+偏移一致）。 */
static int kbd_scan_raw(KbdPos_t *out, int max)
{
    int n = 0;
    for (int i = 0; i < KBD_COL_SEL_COUNT; i++) {
        kbd_set_col(i);
        esp_rom_delay_us(20); /* 等 74HC138 + 走线稳定 */
        for (int j = 0; j < KBD_ROW_COUNT; j++) {
            if (gpio_get_level(KBD_ROW_PINS[j]) == 0) { /* 低=按下 */
                if (n < max) {
                    out[n].x = (i > 3) ? KBD_X_MAP[j].x_1 : KBD_X_MAP[j].x_2;
                    out[n].y = (int8_t)(3 - (i % 4));
                    n++;
                }
            }
        }
    }
    return n;
}

/* 扫描顺序固定(外层 i 升序、内层 j 升序)，故同一组按下键的列表逐字节可比。
 * 若将来改变扫描顺序，此 memcmp 假设失效，需改为集合比较。 */
static bool pos_eq(const KbdPos_t *a, int na, const KbdPos_t *b, int nb)
{
    return na == nb && memcmp(a, b, (size_t)na * sizeof(KbdPos_t)) == 0;
}

static void log_pressed(const KbdPos_t *p, int n)
{
    if (n == 0) {
        ESP_LOGI(TAG, "all released");
        return;
    }
    char buf[128];
    int o = 0;
    for (int k = 0; k < n && o < (int)sizeof(buf) - 8; k++)
        o += snprintf(buf + o, sizeof(buf) - o, " (%d,%d)", p[k].x, p[k].y);
    ESP_LOGI(TAG, "pressed%s", buf);
}

static void hid_keyboard_task(void *arg)
{
    (void)arg;
    kbd_gpio_init();

    KbdPos_t cur[KBD_MAX_PRESSED], prev[KBD_MAX_PRESSED], stable[KBD_MAX_PRESSED];
    int ncur = 0, nprev = 0, nstable = 0;

    while (1) {
        ncur = kbd_scan_raw(cur, KBD_MAX_PRESSED);

        /* 去抖：连续两次扫描一致才认作稳定状态 */
        if (pos_eq(cur, ncur, prev, nprev) && !pos_eq(cur, ncur, stable, nstable)) {
            memcpy(stable, cur, (size_t)ncur * sizeof(KbdPos_t));
            nstable = ncur;

            log_pressed(stable, nstable);
            /* 键值映射上报(后续在此任务内联实现，无跨任务共享)：把 stable[0..nstable)
             * 映射成 HID keycode + modifier，再 tud_hid_keyboard_report()。 */
        }

        memcpy(prev, cur, (size_t)ncur * sizeof(KbdPos_t));
        nprev = ncur;
        vTaskDelay(pdMS_TO_TICKS(15));
    }
}

void hid_keyboard_start(void)
{
    xTaskCreate(hid_keyboard_task, "hid_kbd", 4096, NULL, 5, NULL);
}
