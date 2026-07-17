#pragma once

#include <stdint.h>
#include <stddef.h>

#include "framebuffer.h"
#include "font.h"
#include "spectrum.h"
#include "track.h"

typedef enum {
    UI_PAGE_LOADING = 0,
    UI_PAGE_LOGIN_QR,
    UI_PAGE_NOW_PLAYING,
    UI_PAGE_QUEUE,
    UI_PAGE_SOURCE,
    UI_PAGE_ERROR,
} ui_page_t;

typedef struct {
    uint16_t cover[96 * 96];
    int cover_loaded;
    float smoothed[SPECTRUM_BANDS];
    int visualizer_mode;
    uint16_t theme_color;
    track_t track;
    const track_list_t *queue;
    size_t current_index;
    size_t queue_index;
    ui_page_t page;
    ui_page_t previous_page;
    uint64_t page_opened_ms;
    uint64_t transition_started_ms;
    uint64_t now_ms;
    char status[128];
    uint8_t qr_modules[177 * 177];
    int qr_width;
    font_renderer_t font;
    uint16_t transition_from[UI_WIDTH * UI_HEIGHT];
    uint16_t transition_to[UI_WIDTH * UI_HEIGHT];
} ui_state_t;

int ui_init(ui_state_t *ui);
void ui_close(ui_state_t *ui);
void ui_set_track(ui_state_t *ui, const track_t *track);
void ui_set_status(ui_state_t *ui, const char *status);
int ui_set_login_qr(ui_state_t *ui, const char *url, const char *status);
void ui_set_queue(ui_state_t *ui, const track_list_t *queue,
                  size_t current_index);
void ui_show_page(ui_state_t *ui, ui_page_t page, uint64_t now_ms);
void ui_tick(ui_state_t *ui, uint64_t now_ms);
size_t ui_move_queue_selection(ui_state_t *ui, int direction);
size_t ui_queue_selection(const ui_state_t *ui);
void ui_set_cover(ui_state_t *ui,
                  const uint16_t pixels[96 * 96], uint16_t theme_color);
void ui_render(framebuffer_t *fb, ui_state_t *ui,
               const spectrum_frame_t *spectrum, const int16_t *samples,
               size_t sample_count, uint64_t position_ms, int paused);
