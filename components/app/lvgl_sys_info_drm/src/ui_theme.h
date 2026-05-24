/**
 * ui_theme.h — nothing-design 浅色暖白主题 token 与字体角色
 *
 * 配色遵循 nothing-design：暖白底、深字、红色为中断强调；灰阶即层级。
 * 字体经 FreeType 运行时加载（Space Grotesk / Space Mono / Doto），缺失回退内置。
 */
#ifndef UI_THEME_H
#define UI_THEME_H

#include "lvgl.h"

/* ------- 颜色 token（浅色暖白）------- */
#define NT_COL_BG        lv_color_hex(0xF4F1EA)  /* 暖白背景 */
#define NT_COL_SURFACE   lv_color_hex(0xEAE6DD)  /* 卡片表面 */
#define NT_COL_TEXT      lv_color_hex(0x1A1A18)  /* 主文字（近黑暖调）*/
#define NT_COL_TEXT_SEC  lv_color_hex(0x6E6A62)  /* 次文字 ~60% */
#define NT_COL_TEXT_DIS  lv_color_hex(0xA8A39A)  /* 三级/禁用 ~40% */
#define NT_COL_RED       lv_color_hex(0xD71921)  /* 中断强调红 */

/* ------- 字体角色（三层法则）------- */
typedef struct {
    const lv_font_t *display;  /* Doto，hero 数字 */
    const lv_font_t *heading;  /* Space Grotesk，标题 */
    const lv_font_t *body;     /* Space Grotesk，正文 */
    const lv_font_t *label;    /* Space Mono，ALL CAPS 标签/元数据 */
} ui_fonts_t;

extern ui_fonts_t g_fonts;

/**
 * 初始化主题：加载 FreeType 字体（缺失回退内置），设置默认背景/文字色。
 * 始终返回有效字体角色（回退保证不为 NULL）。
 */
void ui_theme_init(void);

#endif /* UI_THEME_H */
