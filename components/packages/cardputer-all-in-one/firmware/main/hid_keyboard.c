#include "hid_keyboard.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "tusb.h"

static const char *TAG = "hid_kbd";

/*
 * 最小测试任务：等待 USB 枚举完成后，若 HID 就绪则上报一次 KEY_A，
 * 短暂保持后松开（发空报文），随即结束任务。
 * Task2/3 将以此处的 tud_hid_keyboard_report(0, 0, keys) 为接口，
 * 把矩阵扫描得到的 HID keycode 填入 keys[6] + modifier 上报。
 */
static void hid_keyboard_task(void *arg)
{
    (void)arg;

    /* 等待 host 枚举 + HID 接口就绪（3s 余量）。 */
    vTaskDelay(pdMS_TO_TICKS(3000));

    if (tud_hid_ready()) {
        uint8_t keys[6] = {HID_KEY_A, 0, 0, 0, 0, 0};
        tud_hid_keyboard_report(0, 0, keys);
        vTaskDelay(pdMS_TO_TICKS(50));
        tud_hid_keyboard_report(0, 0, NULL); /* 松开 */
        ESP_LOGI(TAG, "test report KEY_A sent");
    } else {
        ESP_LOGW(TAG, "HID not ready, skip test report");
    }

    vTaskDelete(NULL);
}

void hid_keyboard_start(void)
{
    xTaskCreate(hid_keyboard_task, "hid_kbd", 2048, NULL, 5, NULL);
}
