/*
 * bring-up 期屏上状态面板的上屏、脏检查与节流。版式与像素运算在
 * audio_panel_render.c（纯函数，宿主机可测），本文件只管缓冲、节流与 display_blit。
 */
#include "audio_panel.h"

#if CONFIG_TAB5_AUDIO_PANEL

#include "audio_panel_render.h"
#include "display_dsi.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include <string.h>

static const char *TAG = "apanel";

/* 电平条刷新周期。5 Hz：肉眼跟得上，又不至于让 PPA 搬运挤占 USB 收帧的时序。 */
#define METER_PERIOD_US  200000

/*
 * 两块紧凑 RGB565 缓冲，分别对应 display_blit() 的两次调用（display_blit 的输入
 * 契约是 stride == w 的紧凑排列）。分开 blit 是为了别让 5 Hz 的电平条刷新
 * 顺带搬运状态区那 48 KB。
 * 一次分配、不释放：bring-up 工具的生命周期就是整个开机。
 */
static uint16_t *s_status_px;   /* 512×52×2 = 53,248 B */
static uint16_t *s_meter_px;    /* 512×32×2 = 32,768 B */

static char s_lines[AUDIO_PANEL_STATUS_LINES][AUDIO_PANEL_COLS + 1];

/* 节流窗口内的峰值取 max 累积，而不是丢弃 —— 丢弃会让一次拍手正好落在
 * 窗口里而完全看不见，那正是电平条要抓的那类瞬态。 */
static uint16_t s_acc_l, s_acc_r;
static int64_t s_meter_due_us;

static void blit_status(void)
{
    const char *lines[AUDIO_PANEL_STATUS_LINES];

    for (int i = 0; i < AUDIO_PANEL_STATUS_LINES; i++)
        lines[i] = s_lines[i];

    audio_panel_render_status(s_status_px, lines, AUDIO_PANEL_STATUS_LINES);
    display_blit(AUDIO_PANEL_X, AUDIO_PANEL_Y,
                 AUDIO_PANEL_STATUS_W, AUDIO_PANEL_STATUS_H, s_status_px);
}

static void blit_meter(uint16_t peak_l, uint16_t peak_r)
{
    audio_panel_render_meter(s_meter_px, peak_l, peak_r);
    display_blit(AUDIO_PANEL_METER_X, AUDIO_PANEL_METER_Y,
                 AUDIO_PANEL_METER_W, AUDIO_PANEL_METER_H, s_meter_px);
}

esp_err_t audio_panel_init(void)
{
    const size_t status_bytes =
        (size_t)AUDIO_PANEL_STATUS_W * AUDIO_PANEL_STATUS_H * sizeof(uint16_t);
    const size_t meter_bytes =
        (size_t)AUDIO_PANEL_METER_W * AUDIO_PANEL_METER_H * sizeof(uint16_t);

    s_status_px = heap_caps_malloc(status_bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    s_meter_px  = heap_caps_malloc(meter_bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!s_status_px || !s_meter_px) {
        heap_caps_free(s_status_px);
        heap_caps_free(s_meter_px);
        s_status_px = NULL;
        s_meter_px = NULL;
        ESP_LOGE(TAG, "面板缓冲分配失败(%u B)", (unsigned)(status_bytes + meter_bytes));
        return ESP_ERR_NO_MEM;
    }

    /* 先把两块区域画成空面板：这样"面板活着"这件事在任何状态文本到来之前
     * 就已经可见 —— 若这一步没在屏上留下痕迹，问题就在 blit 而不在数据源。 */
    memset(s_lines, 0, sizeof(s_lines));
    blit_status();
    blit_meter(0, 0);
    ESP_LOGI(TAG, "屏上状态面板已启用 (%u B PSRAM)",
             (unsigned)(status_bytes + meter_bytes));
    return ESP_OK;
}

void audio_panel_status(int line, const char *text)
{
    if (!s_status_px || line < 0 || line >= AUDIO_PANEL_STATUS_LINES)
        return;
    if (!text)
        text = "";

    /* 内容没变就不重画：状态行会被无脑重复调用（比如每次探测后），
     * 而每次重画都是一次 48 KB 的 PPA 搬运。 */
    if (strncmp(s_lines[line], text, AUDIO_PANEL_COLS) == 0)
        return;

    strncpy(s_lines[line], text, AUDIO_PANEL_COLS);
    s_lines[line][AUDIO_PANEL_COLS] = '\0';
    blit_status();
}

void audio_panel_levels(uint16_t peak_l, uint16_t peak_r)
{
    if (!s_meter_px)
        return;

    if (peak_l > s_acc_l)
        s_acc_l = peak_l;
    if (peak_r > s_acc_r)
        s_acc_r = peak_r;

    const int64_t now = esp_timer_get_time();
    if (now < s_meter_due_us)
        return;
    s_meter_due_us = now + METER_PERIOD_US;

    blit_meter(s_acc_l, s_acc_r);
    s_acc_l = 0;
    s_acc_r = 0;
}

#else  /* !CONFIG_TAB5_AUDIO_PANEL */

/* 关闭时编译成空实现：调用点不必加条件，未被引用的部分由 --gc-sections 清掉。 */
esp_err_t audio_panel_init(void)
{
    return ESP_OK;
}

void audio_panel_status(int line, const char *text)
{
    (void)line;
    (void)text;
}

void audio_panel_levels(uint16_t peak_l, uint16_t peak_r)
{
    (void)peak_l;
    (void)peak_r;
}

#endif
