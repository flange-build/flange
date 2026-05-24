/**
 * ui_theme.c — 见 ui_theme.h
 */
#include "ui_theme.h"

#include <stdio.h>

#define FONT_DIR "/usr/share/lvgl_sys_info_drm/fonts/"

ui_fonts_t g_fonts;

/* 经 FreeType 加载一个 TTF 字号；失败返回 NULL */
static const lv_font_t *load_ttf(const char *file, uint32_t size)
{
    char path[256];
    snprintf(path, sizeof(path), "%s%s", FONT_DIR, file);
    lv_font_t *f = lv_freetype_font_create(path,
                                           LV_FREETYPE_FONT_RENDER_MODE_BITMAP,
                                           size,
                                           LV_FREETYPE_FONT_STYLE_NORMAL);
    if (!f)
        fprintf(stderr, "[theme] 字体加载失败，回退内置: %s@%u\n", path, size);
    return f;
}

void ui_theme_init(void)
{
    /* 字体角色：FreeType 优先，缺失回退 LVGL 内置 montserrat */
    g_fonts.display = load_ttf("Doto-Variable.ttf", 44);
    g_fonts.heading = load_ttf("SpaceGrotesk-Variable.ttf", 26);
    g_fonts.body    = load_ttf("SpaceGrotesk-Variable.ttf", 16);
    g_fonts.label   = load_ttf("SpaceMono-Regular.ttf", 13);

    if (!g_fonts.display) g_fonts.display = &lv_font_montserrat_16;
    if (!g_fonts.heading) g_fonts.heading = &lv_font_montserrat_16;
    if (!g_fonts.body)    g_fonts.body    = &lv_font_montserrat_14;
    if (!g_fonts.label)   g_fonts.label   = &lv_font_montserrat_14;

    /* 屏幕级默认：暖白底 + 主文字色 + 正文字体（子对象继承） */
    lv_obj_t *scr = lv_screen_active();
    lv_obj_set_style_bg_color(scr, NT_COL_BG, 0);
    lv_obj_set_style_bg_opa(scr, LV_OPA_COVER, 0);
    lv_obj_set_style_text_color(scr, NT_COL_TEXT, 0);
    lv_obj_set_style_text_font(scr, g_fonts.body, 0);
}
