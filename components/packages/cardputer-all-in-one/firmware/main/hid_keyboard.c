#include "hid_keyboard.h"
#include "cardputer_kbd_map.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gpio.h"
#include "esp_rom_sys.h"
#include "esp_log.h"
#include "tusb.h"
#include <string.h>

static const char *TAG = "hid_kbd";

/*
 * 键位 → HID usage 映射（坐标 [y][x] 与 M5Cardputer _key_value_map 一致）。
 * HID 键盘只需"键的身份"：shift 作为 modifier 发给 host，由 host 产生大写/符号，
 * 故不需要 M5 的 value_second(Aa 层)。
 *   hid_base：基础层(M5 value_first 的键身份)
 *   hid_fn  ：fn 层(M5 value_third)，0=该键 fn 层无定义
 * 修饰键位(FN/SHIFT/CTRL/OPT/ALT)在表里填 0，由 is_modifier_pos() 单独处理。
 */
static const uint8_t hid_base[4][14] = {
    {HID_KEY_GRAVE, HID_KEY_1, HID_KEY_2, HID_KEY_3, HID_KEY_4, HID_KEY_5,
     HID_KEY_6, HID_KEY_7, HID_KEY_8, HID_KEY_9, HID_KEY_0, HID_KEY_MINUS,
     HID_KEY_EQUAL, HID_KEY_BACKSPACE},
    {HID_KEY_TAB, HID_KEY_Q, HID_KEY_W, HID_KEY_E, HID_KEY_R, HID_KEY_T,
     HID_KEY_Y, HID_KEY_U, HID_KEY_I, HID_KEY_O, HID_KEY_P, HID_KEY_BRACKET_LEFT,
     HID_KEY_BRACKET_RIGHT, HID_KEY_BACKSLASH},
    {0 /*FN*/, 0 /*SHIFT*/, HID_KEY_A, HID_KEY_S, HID_KEY_D, HID_KEY_F,
     HID_KEY_G, HID_KEY_H, HID_KEY_J, HID_KEY_K, HID_KEY_L, HID_KEY_SEMICOLON,
     HID_KEY_APOSTROPHE, HID_KEY_ENTER},
    {0 /*CTRL*/, 0 /*OPT*/, 0 /*ALT*/, HID_KEY_Z, HID_KEY_X, HID_KEY_C,
     HID_KEY_V, HID_KEY_B, HID_KEY_N, HID_KEY_M, HID_KEY_COMMA, HID_KEY_PERIOD,
     HID_KEY_SLASH, HID_KEY_SPACE},
};

static const uint8_t hid_fn[4][14] = {
    {HID_KEY_ESCAPE, HID_KEY_F1, HID_KEY_F2, HID_KEY_F3, HID_KEY_F4, HID_KEY_F5,
     HID_KEY_F6, HID_KEY_F7, HID_KEY_F8, HID_KEY_F9, HID_KEY_F10, HID_KEY_F11,
     HID_KEY_F12, HID_KEY_DELETE},
    {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0},
    {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, HID_KEY_ARROW_UP, 0, 0},
    {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, HID_KEY_ARROW_LEFT, HID_KEY_ARROW_DOWN,
     HID_KEY_ARROW_RIGHT, 0},
};

/* 修饰/层键位置（x,y）：FN(0,2) SHIFT(1,2) CTRL(0,3) OPT(1,3) ALT(2,3) */
static bool is_modifier_pos(int x, int y)
{
    return (x == 0 && y == 2) || (x == 1 && y == 2) || (x == 0 && y == 3) ||
           (x == 1 && y == 3) || (x == 2 && y == 3);
}

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

/* 把 3 位列选值写到 74HC138 地址线 A0/A1/A2（KBD_COL_PINS[0..2]）。 */
static void kbd_set_col(int sel)
{
    gpio_set_level(KBD_COL_PINS[0], (sel >> 0) & 1);
    gpio_set_level(KBD_COL_PINS[1], (sel >> 1) & 1);
    gpio_set_level(KBD_COL_PINS[2], (sel >> 2) & 1);
}

/* 一次原始扫描 → 按下键位列表(坐标系同 M5 库)，返回数量。
 * x = (i>3)?x_1:x_2；y = 3 - (i%4)（与 M5 库 update() 的 Y 取反+偏移一致）。 */
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

/* 把按下键位集合映射为 HID 报告并上报（在扫描任务内联调用，无跨任务共享）。 */
static void kbd_report(const KbdPos_t *p, int n)
{
    uint8_t modifier = 0;
    bool fn = false;

    /* 第一遍：修饰/层键 */
    for (int k = 0; k < n; k++) {
        int x = p[k].x, y = p[k].y;
        if (x == 0 && y == 2) fn = true;                               /* FN(本地层) */
        else if (x == 1 && y == 2) modifier |= KEYBOARD_MODIFIER_LEFTSHIFT;
        else if (x == 0 && y == 3) modifier |= KEYBOARD_MODIFIER_LEFTCTRL;
        else if (x == 2 && y == 3) modifier |= KEYBOARD_MODIFIER_LEFTALT;
        else if (x == 1 && y == 3) modifier |= KEYBOARD_MODIFIER_LEFTGUI; /* OPT→GUI */
    }

    /* 第二遍：普通键 → usage（最多 6KRO） */
    uint8_t keys[6] = {0};
    int nk = 0;
    for (int k = 0; k < n && nk < 6; k++) {
        int x = p[k].x, y = p[k].y;
        if (x < 0 || x > 13 || y < 0 || y > 3) continue;
        if (is_modifier_pos(x, y)) continue;
        uint8_t u = fn ? hid_fn[y][x] : hid_base[y][x]; /* fn 层无定义(0)则该键不发，与 M5 一致 */
        if (u != 0) keys[nk++] = u;
    }

    ESP_LOGI(TAG, "HID report mod=0x%02x fn=%d keys=%02x %02x %02x %02x %02x %02x",
             modifier, fn, keys[0], keys[1], keys[2], keys[3], keys[4], keys[5]);

    if (tud_hid_ready())
        tud_hid_keyboard_report(0, modifier, nk ? keys : NULL);
}

static void hid_keyboard_task(void *arg)
{
    (void)arg;
    kbd_gpio_init();

    KbdPos_t cur[KBD_MAX_PRESSED], prev[KBD_MAX_PRESSED], stable[KBD_MAX_PRESSED];
    int ncur = 0, nprev = 0, nstable = 0;

    while (1) {
        ncur = kbd_scan_raw(cur, KBD_MAX_PRESSED);

        /* 去抖：连续两次扫描一致才认作稳定状态；变化时映射上报 */
        if (pos_eq(cur, ncur, prev, nprev) && !pos_eq(cur, ncur, stable, nstable)) {
            memcpy(stable, cur, (size_t)ncur * sizeof(KbdPos_t));
            nstable = ncur;
            kbd_report(stable, nstable);
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
