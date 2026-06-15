#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"

static const char *TAG = "aio";

void app_main(void)
{
    int n = 0;
    while (1) {
        ESP_LOGI(TAG, "cardputer-aio alive %d", n++);
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}
