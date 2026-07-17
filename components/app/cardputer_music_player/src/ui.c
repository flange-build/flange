#include "ui.h"

#include <stdio.h>
#include <string.h>

#include <qrencode.h>

#include "theme.h"
#include "text.h"

#define COVER_PATH "/usr/share/cardputer_music_player/midnight-bloom.bmp"
#define PAGE_TRANSITION_MS 160U

static uint16_t darken(uint16_t color, unsigned divisor)
{
    unsigned r = (color >> 11) & 0x1f;
    unsigned g = (color >> 5) & 0x3f;
    unsigned b = color & 0x1f;
    return (uint16_t)(((r / divisor) << 11)
        | ((g / divisor) << 5) | (b / divisor));
}

static void render_background(framebuffer_t *fb, const ui_state_t *ui)
{
    gfx_clear(fb, UI_COLOR_BG);
    if (!ui->cover_loaded)
        return;

    /* 用真实封面低采样并压暗，形成参考稿中的封面氛围回声。 */
    for (int y = 0; y < UI_HEIGHT; y++) {
        for (int x = 0; x < UI_WIDTH; x++) {
            int sx = (x * 96 / UI_WIDTH + 19) % 96;
            int sy = y * 96 / UI_HEIGHT;
            uint16_t color = darken(ui->cover[sy * 96 + sx], 8);
            fb->pixels[y * UI_WIDTH + x] = color;
        }
    }
    for (int radius = 42; radius > 0; radius -= 2) {
        uint16_t color = radius > 24 ? rgb565(13, 8, 10)
                                     : rgb565(18, 9, 12);
        int x = 24 - radius / 2;
        int y = 12 - radius / 3;
        gfx_rect(fb, x, y, radius, 1, color);
    }
}

static void render_cover(framebuffer_t *fb, const ui_state_t *ui)
{
    const int x0 = 9;
    const int y0 = 20;
    gfx_rect(fb, x0 - 1, y0 - 1, 98, 98, UI_COLOR_BORDER);
    if (ui->cover_loaded) {
        for (int y = 0; y < 96; y++) {
            memcpy(&fb->pixels[(y0 + y) * UI_WIDTH + x0],
                   &ui->cover[y * 96], 96 * sizeof(uint16_t));
        }
    } else {
        gfx_rect(fb, x0, y0, 96, 96, UI_COLOR_SURFACE);
        gfx_text(fb, x0 + 15, y0 + 44, "MUSIC", UI_COLOR_ACCENT, 2);
    }
}

static void format_time(char *buffer, size_t size, uint64_t milliseconds)
{
    uint64_t seconds = milliseconds / 1000;
    snprintf(buffer, size, "%llu:%02llu",
             (unsigned long long)(seconds / 60),
             (unsigned long long)(seconds % 60));
}

static void render_transport(framebuffer_t *fb, uint64_t position_ms,
                             uint64_t duration_ms, int paused)
{
    const int icon_x = 116;
    const int text_y = 61;
    char position[16];
    char duration[16];
    if (duration_ms == 0U)
        duration_ms = 180000U;
    uint64_t looped_position = position_ms % duration_ms;
    format_time(position, sizeof(position), looped_position);
    format_time(duration, sizeof(duration), duration_ms);

    if (!paused) {
        gfx_rect(fb, icon_x, text_y - 1, 3, 9, UI_COLOR_ACCENT);
        gfx_rect(fb, icon_x + 6, text_y - 1, 3, 9, UI_COLOR_ACCENT);
    } else {
        for (int row = 0; row < 9; row++) {
            gfx_line(fb, icon_x, text_y - 1 + row,
                     icon_x + row / 2, text_y - 1 + row,
                     UI_COLOR_ACCENT);
        }
    }

    gfx_text(fb, 130, text_y, position, UI_COLOR_TEXT, 1);
    gfx_text(fb, 207, text_y, duration, UI_COLOR_MUTED, 1);
    gfx_rect(fb, 116, 75, 114, 2, UI_COLOR_BORDER);
    int progress = (int)(looped_position * 114U / duration_ms);
    gfx_rect(fb, 116, 75, progress, 2, UI_COLOR_ACCENT);
}

static void render_spectrum(framebuffer_t *fb, ui_state_t *ui,
                            const spectrum_frame_t *spectrum)
{
    const int base_y = 124;
    const int start_x = 116;
    const int bar_width = 5;
    const int gap = 2;
    const int max_height = 40;

    for (int i = 0; i < SPECTRUM_BANDS; i++) {
        float target = spectrum->bands[i];
        if (target >= ui->smoothed[i])
            ui->smoothed[i] = target;
        else
            ui->smoothed[i] = ui->smoothed[i] * 0.72f + target * 0.28f;
        int height = 1 + (int)(ui->smoothed[i] * max_height);
        int x = start_x + i * (bar_width + gap);
        gfx_rect(fb, x, base_y - height, bar_width, height,
                 i % 3 == 1 ? UI_COLOR_ACCENT : UI_COLOR_ACCENT_2);
        gfx_rect(fb, x, base_y - height, bar_width, 1, UI_COLOR_ACCENT);
    }
}

static void render_waveform(framebuffer_t *fb, const int16_t *samples,
                            size_t count)
{
    if (count < 2)
        return;
    const int start_x = 116;
    const int width = 114;
    const int center_y = 103;
    const int amplitude = 18;
    int previous_y = center_y;
    int previous_mirror = center_y;

    for (int x = 0; x < width; x += 3) {
        size_t index = (size_t)x * (count - 1) / (size_t)(width - 1);
        int offset = samples[index] * amplitude / 32768;
        int y = center_y - offset;
        int mirror = center_y + offset;
        if (x > 0) {
            gfx_line(fb, start_x + x - 3, previous_y,
                     start_x + x, y, UI_COLOR_ACCENT);
            gfx_line(fb, start_x + x - 3, previous_mirror,
                     start_x + x, mirror, UI_COLOR_ACCENT_2);
        }
        previous_y = y;
        previous_mirror = mirror;
    }
}

int ui_init(ui_state_t *ui)
{
    memset(ui, 0, sizeof(*ui));
    ui->cover_loaded = bmp_load_rgb565(COVER_PATH, ui->cover, 96, 96) == 0;
    if (!ui->cover_loaded)
        fprintf(stderr, "[ui] 无法加载 %s，使用内置占位\n", COVER_PATH);
    snprintf(ui->track.source, sizeof(ui->track.source), "online");
    snprintf(ui->track.title, sizeof(ui->track.title), "正在加载");
    snprintf(ui->track.artist, sizeof(ui->track.artist), "在线音乐");
    ui->page = UI_PAGE_LOADING;
    ui->previous_page = UI_PAGE_LOADING;
    (void)font_open(&ui->font);
    return 0;
}

void ui_set_track(ui_state_t *ui, const track_t *track)
{
    if (track != NULL)
        ui->track = *track;
}

void ui_set_status(ui_state_t *ui, const char *status)
{
    snprintf(ui->status, sizeof(ui->status), "%s",
             status == NULL ? "" : status);
}

int ui_set_login_qr(ui_state_t *ui, const char *url, const char *status)
{
    QRcode *code = QRcode_encodeString8bit(url, 0, QR_ECLEVEL_L);
    if (code == NULL)
        return -1;
    if (code->width <= 0 || code->width > 177) {
        QRcode_free(code);
        ui->qr_width = 0;
        return -1;
    }
    ui->qr_width = code->width;
    size_t bytes = (size_t)code->width * (size_t)code->width;
    for (size_t i = 0U; i < bytes; i++)
        ui->qr_modules[i] = code->data[i] & 1U;
    QRcode_free(code);
    ui_set_status(ui, status);
    return 0;
}

void ui_set_queue(ui_state_t *ui, const track_list_t *queue,
                  size_t current_index)
{
    ui->queue = queue;
    ui->current_index = current_index;
    ui->queue_index = current_index;
}

void ui_show_page(ui_state_t *ui, ui_page_t page, uint64_t now_ms)
{
    if (ui->page == page) {
        ui->page_opened_ms = now_ms;
        return;
    }
    ui->previous_page = ui->page;
    ui->page = page;
    ui->page_opened_ms = now_ms;
    ui->transition_started_ms = now_ms;
}

void ui_tick(ui_state_t *ui, uint64_t now_ms)
{
    ui->now_ms = now_ms;
    if (ui->page == UI_PAGE_SOURCE
            && now_ms - ui->page_opened_ms >= 5000U)
        ui_show_page(ui, UI_PAGE_NOW_PLAYING, now_ms);
}

size_t ui_move_queue_selection(ui_state_t *ui, int direction)
{
    if (ui->queue == NULL || ui->queue->count == 0U)
        return 0U;
    if (direction < 0) {
        ui->queue_index = ui->queue_index == 0U
            ? ui->queue->count - 1U : ui->queue_index - 1U;
    } else if (direction > 0) {
        ui->queue_index = (ui->queue_index + 1U) % ui->queue->count;
    }
    return ui->queue_index;
}

size_t ui_queue_selection(const ui_state_t *ui)
{
    return ui->queue_index;
}

void ui_set_cover(ui_state_t *ui,
                  const uint16_t pixels[96 * 96], uint16_t theme_color)
{
    memcpy(ui->cover, pixels, sizeof(ui->cover));
    ui->cover_loaded = 1;
    ui->theme_color = theme_color;
}

static void format_source_label(const track_t *track,
                                char *label, size_t size)
{
    if (strcmp(track->source, "douyin") == 0) {
        if (track->rank > 0U)
            snprintf(label, size, "抖音热歌 #%u%s", track->rank,
                     track->audio_url[0] == '\0' ? " / 仅展示" : "");
        else
            snprintf(label, size, "抖音热歌%s",
                     track->audio_url[0] == '\0' ? " / 仅展示" : "");
    } else if (strcmp(track->source, "qishui") == 0) {
        snprintf(label, size, "汽水音乐 / %s",
                 track->audio_url[0] == '\0' ? "仅展示" : "已授权");
    } else if (strcmp(track->source, "netease") == 0) {
        const char *state = !track->audio_resolved
            ? "待加载"
            : (track->audio_url[0] == '\0'
                ? "无播放权限" : "标准音质");
        snprintf(label, size, "网易云歌单 / %s", state);
    } else {
        snprintf(label, size, "%s%s", track->source,
                 track->audio_url[0] == '\0' ? " / 不可播放" : "");
    }
}

static void render_queue_page(framebuffer_t *fb, ui_state_t *ui)
{
    gfx_clear(fb, UI_COLOR_BG);
    gfx_rect(fb, 0, 0, UI_WIDTH, 17, UI_COLOR_SURFACE);
    if (!ui->font.ready) {
        gfx_text(fb, 8, 5, "QUEUE", UI_COLOR_TEXT, 1);
        return;
    }
    font_draw_utf8(&ui->font, fb, 8, 4, "播放队列",
                   UI_COLOR_TEXT, 11, 120);
    font_draw_utf8(&ui->font, fb, 181, 5, "Q 返回",
                   UI_COLOR_MUTED, 8, 55);
    if (ui->queue == NULL || ui->queue->count == 0U) {
        font_draw_utf8(&ui->font, fb, 8, 35, "队列为空",
                       UI_COLOR_MUTED, 10, 220);
        return;
    }
    size_t start = ui->queue_index > 2U ? ui->queue_index - 2U : 0U;
    if (start + 5U > ui->queue->count && ui->queue->count > 5U)
        start = ui->queue->count - 5U;
    for (size_t row = 0; row < 5U && start + row < ui->queue->count; row++) {
        size_t index = start + row;
        const track_t *track = &ui->queue->items[index];
        int y = 22 + (int)row * 22;
        int selected = index == ui->queue_index;
        uint16_t title_color = selected
            ? UI_COLOR_TEXT : UI_COLOR_MUTED;
        if (selected)
            gfx_rect(fb, 6, y - 3, 228, 18, UI_COLOR_SURFACE);
        if (index == ui->current_index)
            gfx_rect(fb, 3, y - 2, 3, 17, UI_COLOR_ACCENT);
        char rank[16];
        snprintf(rank, sizeof(rank), "%02u",
                 track->rank > 0U ? track->rank : (unsigned)index + 1U);
        font_draw_utf8(&ui->font, fb, 10, y, rank,
                       UI_COLOR_ACCENT, 9, 22);
        font_draw_utf8(&ui->font, fb, 37, y, track->title,
                       title_color, 10, 151);
        font_draw_utf8(&ui->font, fb, 190, y,
                       !track->audio_resolved
                           ? "待加载"
                           : (track->audio_url[0] == '\0'
                               ? "仅展示" : "可播放"),
                       track->audio_url[0] == '\0'
                           ? UI_COLOR_MUTED : UI_COLOR_ACCENT,
                       8, 45);
    }
}

static void render_source_page(framebuffer_t *fb, ui_state_t *ui)
{
    gfx_clear(fb, UI_COLOR_BG);
    gfx_rect(fb, 0, 0, UI_WIDTH, 17, UI_COLOR_SURFACE);
    if (!ui->font.ready) {
        gfx_text(fb, 8, 5, "SOURCE", UI_COLOR_TEXT, 1);
        return;
    }
    char source[96];
    format_source_label(&ui->track, source, sizeof(source));
    font_draw_utf8(&ui->font, fb, 8, 4, "内容来源",
                   UI_COLOR_TEXT, 11, 120);
    font_draw_utf8(&ui->font, fb, 181, 5, "Q 返回",
                   UI_COLOR_MUTED, 8, 55);
    font_draw_utf8(&ui->font, fb, 10, 27, source,
                   UI_COLOR_ACCENT, 11, 220);
    font_draw_utf8(&ui->font, fb, 10, 52,
                   ui->track.audio_url[0] == '\0'
                       ? "元数据可用 · 未提供授权音频 URL"
                       : "已提供授权音频 URL · TLS 校验开启",
                   UI_COLOR_TEXT, 9, 220);
    font_draw_utf8(&ui->font, fb, 10, 77,
                   "分享页不会进入音频解码器",
                   UI_COLOR_MUTED, 9, 220);
    font_draw_utf8(&ui->font, fb, 10, 107,
                   "R 刷新  ·  A/D 切歌  ·  V 可视化",
                   UI_COLOR_MUTED, 8, 220);
}

static void render_loading_page(framebuffer_t *fb, ui_state_t *ui)
{
    gfx_clear(fb, UI_COLOR_BG);
    gfx_rect(fb, 0, 0, UI_WIDTH, 3, UI_COLOR_ACCENT);
    if (ui->font.ready) {
        font_draw_utf8(&ui->font, fb, 18, 35, "正在连接在线音乐",
                       UI_COLOR_TEXT, 15, 204);
        font_draw_utf8(&ui->font, fb, 18, 62,
                       ui->status[0] == '\0' ? "加载歌单与播放地址"
                                             : ui->status,
                       UI_COLOR_MUTED, 9, 204);
    } else {
        gfx_text(fb, 18, 38, "LOADING MUSIC", UI_COLOR_TEXT, 2);
    }
    int active = (int)((ui->now_ms / 180U) % 6U);
    for (int i = 0; i < 6; i++) {
        int height = i == active ? 16 : 6;
        gfx_rect(fb, 76 + i * 16, 105 - height, 9, height,
                 i <= active ? UI_COLOR_ACCENT : UI_COLOR_BORDER);
    }
}

static void render_login_qr_page(framebuffer_t *fb, ui_state_t *ui)
{
    gfx_clear(fb, UI_COLOR_BG);
    gfx_rect(fb, 0, 0, UI_WIDTH, 3, UI_COLOR_ACCENT);
    if (ui->qr_width > 0) {
        int scale = 108 / (ui->qr_width + 8);
        if (scale < 1)
            scale = 1;
        int total = (ui->qr_width + 8) * scale;
        int x0 = 5 + (108 - total) / 2;
        int y0 = 3 + (132 - total) / 2;
        gfx_rect(fb, x0, y0, total, total, rgb565(255, 255, 255));
        for (int y = 0; y < ui->qr_width; y++) {
            for (int x = 0; x < ui->qr_width; x++) {
                if (ui->qr_modules[y * ui->qr_width + x] != 0U) {
                    gfx_rect(fb, x0 + (x + 4) * scale,
                             y0 + (y + 4) * scale,
                             scale, scale, rgb565(0, 0, 0));
                }
            }
        }
    }
    if (ui->font.ready) {
        font_draw_utf8(&ui->font, fb, 119, 19, "扫码登录",
                       UI_COLOR_TEXT, 15, 112);
        font_draw_utf8(&ui->font, fb, 119, 47,
                       "打开网易云音乐 App",
                       UI_COLOR_MUTED, 9, 112);
        font_draw_utf8(&ui->font, fb, 119, 64,
                       "扫描左侧二维码",
                       UI_COLOR_MUTED, 9, 112);
        font_draw_utf8(&ui->font, fb, 119, 91,
                       ui->status[0] == '\0' ? "等待扫码" : ui->status,
                       UI_COLOR_ACCENT, 10, 112);
        font_draw_utf8(&ui->font, fb, 119, 116,
                       "R 刷新二维码",
                       UI_COLOR_MUTED, 8, 112);
    } else {
        gfx_text(fb, 119, 22, "NCM LOGIN", UI_COLOR_TEXT, 1);
        gfx_text(fb, 119, 92, "SCAN QR", UI_COLOR_ACCENT, 1);
    }
}

static void render_error_page(framebuffer_t *fb, ui_state_t *ui)
{
    gfx_clear(fb, UI_COLOR_BG);
    gfx_rect(fb, 0, 0, UI_WIDTH, 3, UI_COLOR_ACCENT);
    if (ui->font.ready) {
        font_draw_utf8(&ui->font, fb, 18, 29, "在线音乐暂不可用",
                       UI_COLOR_TEXT, 15, 204);
        font_draw_utf8(&ui->font, fb, 18, 58,
                       ui->status[0] == '\0' ? "请检查网络或音源配置"
                                             : ui->status,
                       UI_COLOR_MUTED, 9, 204);
        font_draw_utf8(&ui->font, fb, 18, 96,
                       "R 重试  ·  W/S 查看队列",
                       UI_COLOR_ACCENT, 10, 204);
    } else {
        gfx_text(fb, 18, 34, "MUSIC UNAVAILABLE", UI_COLOR_TEXT, 1);
        gfx_text(fb, 18, 62, "PRESS R TO RETRY", UI_COLOR_ACCENT, 1);
    }
}

static void render_now_playing_page(framebuffer_t *fb, ui_state_t *ui,
                                    const spectrum_frame_t *spectrum,
                                    const int16_t *samples,
                                    size_t sample_count,
                                    uint64_t position_ms, int paused)
{
    char source_label[96];
    char title[TRACK_TITLE_SIZE];
    format_source_label(&ui->track, source_label, sizeof(source_label));
    if (text_ellipsize_utf8(ui->track.title, 10U,
                            title, sizeof(title)) < 0)
        snprintf(title, sizeof(title), "%s", ui->track.title);
    render_background(fb, ui);
    render_cover(fb, ui);

    if (ui->font.ready) {
        font_draw_utf8(&ui->font, fb, 116, 8, source_label,
                       UI_COLOR_ACCENT, 9, 114);
        font_draw_utf8(&ui->font, fb, 116, 24, title,
                       UI_COLOR_TEXT, 15, 114);
        font_draw_utf8(&ui->font, fb, 116, 43, ui->track.artist,
                       UI_COLOR_MUTED, 9, 114);
    } else {
        gfx_text(fb, 116, 10, "ONLINE", UI_COLOR_ACCENT, 1);
        gfx_text(fb, 116, 27, "NOW PLAYING", UI_COLOR_TEXT, 1);
        gfx_text(fb, 116, 44, "MUSIC", UI_COLOR_MUTED, 1);
    }

    render_transport(fb, position_ms, ui->track.duration_ms, paused);
    if (ui->status[0] != '\0' && ui->font.ready) {
        gfx_rect(fb, 114, 80, 118, 13, UI_COLOR_BG);
        font_draw_utf8(&ui->font, fb, 116, 82, ui->status,
                       UI_COLOR_ACCENT, 8, 112);
    }
    if (ui->visualizer_mode == 0)
        render_spectrum(fb, ui, spectrum);
    else
        render_waveform(fb, samples, sample_count);
}

static void render_page(framebuffer_t *fb, ui_state_t *ui, ui_page_t page,
                        const spectrum_frame_t *spectrum,
                        const int16_t *samples, size_t sample_count,
                        uint64_t position_ms, int paused)
{
    switch (page) {
    case UI_PAGE_LOADING:
        render_loading_page(fb, ui);
        break;
    case UI_PAGE_LOGIN_QR:
        render_login_qr_page(fb, ui);
        break;
    case UI_PAGE_QUEUE:
        render_queue_page(fb, ui);
        break;
    case UI_PAGE_SOURCE:
        render_source_page(fb, ui);
        break;
    case UI_PAGE_ERROR:
        render_error_page(fb, ui);
        break;
    case UI_PAGE_NOW_PLAYING:
        render_now_playing_page(fb, ui, spectrum, samples,
                                sample_count, position_ms, paused);
        break;
    }
}

static uint16_t scale_color(uint16_t color, unsigned numerator)
{
    unsigned r = ((color >> 11) & 0x1fU) * numerator / 100U;
    unsigned g = ((color >> 5) & 0x3fU) * numerator / 100U;
    unsigned b = (color & 0x1fU) * numerator / 100U;
    return (uint16_t)((r << 11) | (g << 5) | b);
}

static void render_transition(framebuffer_t *fb, ui_state_t *ui,
                              uint64_t elapsed_ms)
{
    uint64_t remaining = PAGE_TRANSITION_MS - elapsed_ms;
    uint64_t duration_cubed = (uint64_t)PAGE_TRANSITION_MS
        * PAGE_TRANSITION_MS * PAGE_TRANSITION_MS;
    uint64_t remaining_cubed = remaining * remaining * remaining;
    int shift = (int)((uint64_t)UI_WIDTH
        * (duration_cubed - remaining_cubed) / duration_cubed);
    int new_start = UI_WIDTH - shift;
    unsigned old_brightness = 100U - (unsigned)(elapsed_ms * 50U
        / PAGE_TRANSITION_MS);
    unsigned new_brightness = 60U + (unsigned)(elapsed_ms * 40U
        / PAGE_TRANSITION_MS);

    for (int y = 0; y < UI_HEIGHT; y++) {
        for (int x = 0; x < UI_WIDTH; x++) {
            if (x >= new_start) {
                uint16_t color = ui->transition_to[
                    y * UI_WIDTH + x - new_start
                ];
                fb->pixels[y * UI_WIDTH + x] = scale_color(
                    color, new_brightness
                );
            } else {
                uint16_t color = ui->transition_from[
                    y * UI_WIDTH + x + shift
                ];
                fb->pixels[y * UI_WIDTH + x] = scale_color(
                    color, old_brightness
                );
            }
        }
    }
}

void ui_close(ui_state_t *ui)
{
    font_close(&ui->font);
}

void ui_render(framebuffer_t *fb, ui_state_t *ui,
               const spectrum_frame_t *spectrum, const int16_t *samples,
               size_t sample_count, uint64_t position_ms, int paused)
{
    uint64_t elapsed_ms = ui->now_ms - ui->transition_started_ms;
    if (ui->page != ui->previous_page
            && elapsed_ms < PAGE_TRANSITION_MS) {
        render_page(fb, ui, ui->previous_page, spectrum, samples,
                    sample_count, position_ms, paused);
        memcpy(ui->transition_from, fb->pixels,
               sizeof(ui->transition_from));
        render_page(fb, ui, ui->page, spectrum, samples,
                    sample_count, position_ms, paused);
        memcpy(ui->transition_to, fb->pixels,
               sizeof(ui->transition_to));
        render_transition(fb, ui, elapsed_ms);
    } else {
        ui->previous_page = ui->page;
        render_page(fb, ui, ui->page, spectrum, samples,
                    sample_count, position_ms, paused);
    }
    framebuffer_present(fb);
}
