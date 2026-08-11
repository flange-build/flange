#include "display_dsi.h"
#include "esp_log.h"

static const char *TAG = "disp";

esp_err_t display_init(void)
{
    ESP_LOGW(TAG, "display stub: 面板未初始化（Task 2 实现）");
    return ESP_OK;
}

void display_blit(int x, int y, int w, int h, const void *pixels)
{
    (void)pixels;
    ESP_LOGI(TAG, "blit stub %dx%d @(%d,%d)", w, h, x, y);
}
