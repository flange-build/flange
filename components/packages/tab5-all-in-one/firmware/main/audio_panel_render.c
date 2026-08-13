/*
 * bring-up 屏上状态面板的渲染。纯像素运算，见 audio_panel_render.h 的说明。
 *
 * 画布是 GUD 坐标系（640×360 横向）里的两块小矩形，各自紧凑排列、单独上屏；
 * 上屏时 PPA 会 2× 放大并旋转 90°，所以这里 1× 的 8×16 字在面板上是 16×32。
 */
#include "audio_panel_render.h"
#include "standby_screen.h"   /* 绘制原语 + STANDBY_DOTS_* + STANDBY_RGB565 */
#include "tab5_pins.h"        /* GUD_W / GUD_H */
#include "font8x16.h"         /* 只取 FONT8X16_W/H 两个宏做版式换算；字模表本身
                               * 未被引用，故本 TU 不会生成第二份副本 */

/* ---------------- 配色 ----------------
 *
 * 背景刻意与待机画面的 C_BG 取同一个值：面板贴在待机画面下方，背景不一致会出现
 * 一块明显的深浅拼缝。文字/条色沿用待机画面的正文灰与状态琥珀，不另立一套。
 */
#define C_PANEL_BG    STANDBY_RGB565(0x0F, 0x11, 0x15)   /* 实显 #081014，同待机背景 */
#define C_PANEL_TEXT  STANDBY_RGB565(0xC8, 0xCD, 0xD4)   /* 实显 #C8CCD0，正文 */
#define C_PANEL_BAR   STANDBY_RGB565(0xF0, 0xA0, 0x30)   /* 实显 #F0A030，电平条 */

/* ---------------- 版式约束 ----------------
 *
 * 与 standby_screen.c 里那批断言同一用意：版式关系钉在编译期，改数字时先炸。
 */
_Static_assert(AUDIO_PANEL_Y >= STANDBY_DOTS_Y + STANDBY_DOTS_H,
               "面板必须在待机动画的等待点下方：两者都在周期性重画，重叠会互相覆盖");
_Static_assert(AUDIO_PANEL_X + AUDIO_PANEL_STATUS_W <= GUD_W, "状态区右边缘出画");
_Static_assert(AUDIO_PANEL_METER_Y + AUDIO_PANEL_METER_H <= GUD_H, "电平条下边缘出画");
_Static_assert(AUDIO_PANEL_STATUS_H == AUDIO_PANEL_STATUS_LINES * FONT8X16_H,
               "状态区高度必须正好装下整数行");
_Static_assert(AUDIO_PANEL_METER_X + AUDIO_PANEL_METER_W <= GUD_W, "电平条右边缘出画");
_Static_assert(AUDIO_PANEL_Y + AUDIO_PANEL_STATUS_H <= AUDIO_PANEL_METER_Y,
               "状态区与电平条不能重叠：两者分别 blit，重叠等于互相覆盖");

/* ---------------- 电平条一行的内部版式 ----------------
 *
 *  x=0        16                          156   164        204
 *  ┌──┬────────────────────────────────┬────┬──────────┐
 *  │L │██████████████                  │    │    1234  │   y+3..y+13 是条
 *  └──┴────────────────────────────────┴────┴──────────┘
 */
#define METER_ROW_H     16
#define METER_LABEL_X   0
#define METER_BAR_X     16
#define METER_BAR_Y     3                     /* 行内上边距，条上下各留 3 px */
#define METER_BAR_H     10
#define METER_VAL_DIGITS 5                    /* 满刻度 32768 就是 5 位 */
#define METER_VAL_X     (METER_BAR_X + AUDIO_PANEL_BAR_W + 8)

_Static_assert(AUDIO_PANEL_METER_H == 2 * METER_ROW_H, "电平条正好两行：L 与 R");
_Static_assert(METER_BAR_Y + METER_BAR_H <= METER_ROW_H, "条的高度超出行高");
_Static_assert(METER_VAL_X + METER_VAL_DIGITS * FONT8X16_W <= AUDIO_PANEL_METER_W,
               "峰值数字右边缘超出电平条区域");
_Static_assert(METER_BAR_X + AUDIO_PANEL_BAR_W <= METER_VAL_X, "满格的条会压住峰值数字");

uint16_t audio_panel_bar_len(uint16_t peak)
{
    if (peak >= AUDIO_PANEL_PEAK_FULL)
        return AUDIO_PANEL_BAR_W;
    return (uint16_t)(((uint32_t)peak * AUDIO_PANEL_BAR_W) / AUDIO_PANEL_PEAK_FULL);
}

/*
 * 峰值 → 定宽 5 位十进制。补前导零而不是补空格：等宽字体下数字位置完全不动，
 * 快速变化时更容易看出量级，也免得"1234 "与" 1234"这类对齐错觉。
 */
static void fmt_u5(char out[METER_VAL_DIGITS + 1], uint16_t v)
{
    for (int i = METER_VAL_DIGITS - 1; i >= 0; i--) {
        out[i] = (char)('0' + v % 10);
        v /= 10;
    }
    out[METER_VAL_DIGITS] = '\0';
}

static void render_meter_row(const standby_canvas_t *c, int row, char label, uint16_t peak)
{
    const int y = row * METER_ROW_H;
    const char lbl[2] = { label, '\0' };
    char val[METER_VAL_DIGITS + 1];

    standby_draw_text(c, METER_LABEL_X, y, lbl, C_PANEL_TEXT, 1);
    /* 条长为 0 时 standby_fill_rect 什么都不画，正好是"静音就是空条" */
    standby_fill_rect(c, METER_BAR_X, y + METER_BAR_Y,
                      (int)audio_panel_bar_len(peak), METER_BAR_H, C_PANEL_BAR);
    fmt_u5(val, peak);
    standby_draw_text(c, METER_VAL_X, y, val, C_PANEL_TEXT, 1);
}

void audio_panel_render_meter(uint16_t *buf, uint16_t peak_l, uint16_t peak_r)
{
    const standby_canvas_t c = {
        .px = buf, .w = AUDIO_PANEL_METER_W, .h = AUDIO_PANEL_METER_H
    };

    standby_fill_rect(&c, 0, 0, AUDIO_PANEL_METER_W, AUDIO_PANEL_METER_H, C_PANEL_BG);
    render_meter_row(&c, 0, 'L', peak_l);
    render_meter_row(&c, 1, 'R', peak_r);
}

void audio_panel_render_status(uint16_t *buf, const char *const *lines, int n)
{
    const standby_canvas_t c = {
        .px = buf, .w = AUDIO_PANEL_STATUS_W, .h = AUDIO_PANEL_STATUS_H
    };

    standby_fill_rect(&c, 0, 0, AUDIO_PANEL_STATUS_W, AUDIO_PANEL_STATUS_H, C_PANEL_BG);

    if (n > AUDIO_PANEL_STATUS_LINES)
        n = AUDIO_PANEL_STATUS_LINES;

    for (int i = 0; i < n; i++) {
        /* 显式截到 AUDIO_PANEL_COLS 列。standby_fill_rect 的钳位本来也不会越界写，
         * 但那样会为画外的每个字符白跑一遍字形循环，且"截断"这条约定就只存在于
         * 注释里、没法在宿主机上单独验。 */
        char row[AUDIO_PANEL_COLS + 1];
        int k = 0;

        if (!lines[i])
            continue;
        while (k < AUDIO_PANEL_COLS && lines[i][k]) {
            row[k] = lines[i][k];
            k++;
        }
        row[k] = '\0';
        standby_draw_text(&c, 0, i * FONT8X16_H, row, C_PANEL_TEXT, 1);
    }
}
