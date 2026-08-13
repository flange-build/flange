/*
 * 待机画面渲染。纯像素运算，见 standby_screen.h 的说明。
 *
 * 画布就是 GUD 坐标系（640×360 横向）；上屏时 PPA 会 2× 放大并旋转 90°，
 * 所以这里的 1 px 在面板上是 2×2 px、8×16 的字在面板上是 16×32。
 */
#include "standby_screen.h"
#include "font8x16.h"
#include "tab5_pins.h"   /* GUD_W / GUD_H */

#include <string.h>

/* ---------------- 配色 ----------------
 *
 * 深色但不纯黑，长时间挂机不刺眼；文字浅灰，状态词用琥珀拉开层次。
 * RGB565 是有损的（R/B 5 bit、G 6 bit），下表右侧写的是**转换后实际显示**的
 * 24 bit 值（低位补 0），日后调色请对着它看，不要对着左边的设计值。
 * 打包宏 STANDBY_RGB565() 在头文件里（面板也要用同一套换算）。
 */
#define C_BG      STANDBY_RGB565(0x0F, 0x11, 0x15)   /* #0F1115 → 0x0882 实显 #081014 背景 */
#define C_SCREEN  STANDBY_RGB565(0x16, 0x1A, 0x21)   /* #161A21 → 0x10C4 实显 #101820 图标内屏 */
#define C_BEZEL   STANDBY_RGB565(0x6E, 0x76, 0x81)   /* #6E7681 → 0x6BB0 实显 #687480 图标边框 */
#define C_TEXT    STANDBY_RGB565(0xC8, 0xCD, 0xD4)   /* #C8CDD4 → 0xCE7A 实显 #C8CCD0 正文 */
#define C_AMBER   STANDBY_RGB565(0xF0, 0xA0, 0x30)   /* #F0A030 → 0xF506 实显 #F0A030 状态色 */
#define C_DIM     STANDBY_RGB565(0x8A, 0x92, 0x9C)   /* #8A929C → 0x8C93 实显 #889098 脚注 */
#define C_RULE    STANDBY_RGB565(0x2A, 0x2F, 0x38)   /* #2A2F38 → 0x2967 实显 #282C38 分隔线 */

/* ---------------- 文案与版式 ----------------
 *
 * 文案一律英文：显示器 OSD 的通用惯例（"NO SIGNAL"），且中文点阵要带整个 CJK
 * 字库，几十上百 KB flash，对一块开机三秒就被 host 覆盖的画面完全不划算。
 *
 * 横向位置全部由字符数算出来（TEXT_X 宏），不手填 —— 手填的常数改文案就错位，
 * 而错位在屏上未必一眼看得出来。纵向是手排的，见下面的排布图。
 */
#define TEXT_W(s, scale)  ((int)(sizeof(s) - 1) * FONT8X16_W * (scale))
#define TEXT_X(s, scale)  ((GUD_W - TEXT_W((s), (scale))) / 2)

#define TITLE      "NO SIGNAL"
#define TITLE_SC   3                 /* 24×48 */
#define TITLE_Y    164

#define SUB        "Waiting for USB host"
#define SUB_SC     2                 /* 16×32 */
#define SUB_Y      236

#define FOOT1      "M5Stack Tab5  |  USB Display"
#define FOOT1_Y    310
#define FOOT2      "640 x 360 RGB565  |  USB 16d0:10a9"
#define FOOT2_Y    330               /* 底边留 360-330-16 = 14 px */

/* 显示器图标：外框 + 下巴上一颗琥珀电源灯 + 颈 + 底座 */
#define ICON_X     260
#define ICON_Y     40
#define ICON_W     120
#define ICON_H     76                /* 40..116 */
#define ICON_BEZ   3                 /* 边框厚度（下巴另算，见下） */
#define ICON_CHIN  8                 /* 下巴高度，给电源灯留位置 */
#define NECK_W     16
#define NECK_H     10                /* 116..126 */
#define BASE_W     64
#define BASE_H     5                 /* 126..131 */
#define LED_W      3            /* 下巴净高只有 5 px（108..113），灯要留出上下缝 */
#define LED_H      3

#define RULE_Y     292
#define RULE_W     416               /* 112..528 */

/* 等待点必须紧接在副标题右侧，否则动画会跟文字脱节或叠上去。
 * 两者的关系在编译期钉死，改文案/字号时这条断言会先炸。 */
_Static_assert(TEXT_X(SUB, SUB_SC) + TEXT_W(SUB, SUB_SC) == STANDBY_DOTS_X,
               "等待点的 X 必须等于副标题右边缘");
_Static_assert(SUB_Y == STANDBY_DOTS_Y, "等待点的 Y 必须与副标题同基线");
_Static_assert(STANDBY_DOTS_W == 3 * FONT8X16_W * SUB_SC, "等待点最多 3 个字符宽");
_Static_assert(STANDBY_DOTS_H == FONT8X16_H * SUB_SC, "等待点高度 = 副标题行高");
_Static_assert(STANDBY_DOTS_X + STANDBY_DOTS_W <= GUD_W, "等待点右边缘出画");

/* ---------------- 绘制原语 ----------------
 *
 * standby_canvas_t / standby_fill_rect / standby_draw_text 在头文件里导出，
 * 供 audio_panel_render.c 复用；draw_frame / draw_char 只有本文件用，保持 static。
 */

/* 填充矩形。整条绘制链只有这一个函数写像素，边界钳位因此只需在这里做对一次。 */
void standby_fill_rect(const standby_canvas_t *c, int x, int y, int w, int h, uint16_t color)
{
    int x0 = x < 0 ? 0 : x;
    int y0 = y < 0 ? 0 : y;
    int x1 = x + w > c->w ? c->w : x + w;
    int y1 = y + h > c->h ? c->h : y + h;

    for (int yy = y0; yy < y1; yy++)
        for (int xx = x0; xx < x1; xx++)
            c->px[yy * c->w + xx] = color;
}

/* 1 像素粗的矩形线框（只画边，不填内部） */
static void draw_frame(const standby_canvas_t *c, int x, int y, int w, int h,
                       int thick, uint16_t color)
{
    standby_fill_rect(c, x, y, w, thick, color);                    /* 上 */
    standby_fill_rect(c, x, y + h - thick, w, thick, color);        /* 下 */
    standby_fill_rect(c, x, y, thick, h, color);                    /* 左 */
    standby_fill_rect(c, x + w - thick, y, thick, h, color);        /* 右 */
}

/*
 * 画一个字形，整数倍放大：字模的 1 个点画成 scale×scale 的实心方块。
 * 只有一份 8×16 字体，字号层次全靠这个倍数（1×/2×/3×）。
 */
static void draw_char(const standby_canvas_t *c, int x, int y, char ch,
                      uint16_t color, int scale)
{
    unsigned char u = (unsigned char)ch;
    if (u < FONT8X16_FIRST || u > FONT8X16_LAST)
        u = '?';   /* 表外字符画成问号，而不是静默吞掉 */

    const uint8_t *glyph = font8x16[u - FONT8X16_FIRST];
    for (int row = 0; row < FONT8X16_H; row++) {
        uint8_t bits = glyph[row];
        if (!bits)
            continue;
        for (int col = 0; col < FONT8X16_W; col++)
            if (bits & (0x80 >> col))   /* bit7 = 最左像素 */
                standby_fill_rect(c, x + col * scale, y + row * scale, scale, scale, color);
    }
}

void standby_draw_text(const standby_canvas_t *c, int x, int y, const char *s,
                       uint16_t color, int scale)
{
    for (; *s; s++, x += FONT8X16_W * scale)
        draw_char(c, x, y, *s, color, scale);
}

/* ---------------- 画面 ----------------
 *
 *  y=40   ┌────────────┐        显示器线框（内屏更深，下巴上一颗琥珀电源灯）
 *         │            │
 *  y=116  └─────┬──────┘
 *  y=131      ──┴──                底座
 *
 *  y=164        NO SIGNAL          3× 琥珀
 *  y=236   Waiting for USB host…   2× 浅灰，末尾三点循环
 *  y=292   ──────────────────      分隔线
 *  y=310   M5Stack Tab5 | USB Display          1× 暗灰
 *  y=330   640 x 360 RGB565 | USB 16d0:10a9    1× 暗灰
 */
void standby_render(uint16_t *buf)
{
    const standby_canvas_t c = { .px = buf, .w = GUD_W, .h = GUD_H };

    standby_fill_rect(&c, 0, 0, GUD_W, GUD_H, C_BG);

    /* 显示器图标 */
    const int inner_h = ICON_H - ICON_BEZ - ICON_CHIN;
    standby_fill_rect(&c, ICON_X + ICON_BEZ, ICON_Y + ICON_BEZ,
              ICON_W - 2 * ICON_BEZ, inner_h, C_SCREEN);
    draw_frame(&c, ICON_X, ICON_Y, ICON_W, ICON_H, ICON_BEZ, C_BEZEL);
    standby_fill_rect(&c, ICON_X + ICON_W - 12, ICON_Y + ICON_BEZ + inner_h + 1,
              LED_W, LED_H, C_AMBER);                       /* 下巴上的电源灯 */
    standby_fill_rect(&c, ICON_X + (ICON_W - NECK_W) / 2, ICON_Y + ICON_H,
              NECK_W, NECK_H, C_BEZEL);                     /* 颈 */
    standby_fill_rect(&c, ICON_X + (ICON_W - BASE_W) / 2, ICON_Y + ICON_H + NECK_H,
              BASE_W, BASE_H, C_BEZEL);                     /* 底座 */

    standby_draw_text(&c, TEXT_X(TITLE, TITLE_SC), TITLE_Y, TITLE, C_AMBER, TITLE_SC);
    standby_draw_text(&c, TEXT_X(SUB, SUB_SC), SUB_Y, SUB, C_TEXT, SUB_SC);

    standby_fill_rect(&c, (GUD_W - RULE_W) / 2, RULE_Y, RULE_W, 1, C_RULE);

    standby_draw_text(&c, TEXT_X(FOOT1, 1), FOOT1_Y, FOOT1, C_DIM, 1);
    standby_draw_text(&c, TEXT_X(FOOT2, 1), FOOT2_Y, FOOT2, C_DIM, 1);
}

void standby_render_dots(uint16_t *buf, int n_dots)
{
    const standby_canvas_t c = { .px = buf, .w = STANDBY_DOTS_W, .h = STANDBY_DOTS_H };
    char dots[4] = "";

    if (n_dots < 0)
        n_dots = 0;
    if (n_dots > 3)
        n_dots = 3;
    memset(dots, '.', (size_t)n_dots);
    dots[n_dots] = '\0';

    standby_fill_rect(&c, 0, 0, STANDBY_DOTS_W, STANDBY_DOTS_H, C_BG);
    standby_draw_text(&c, 0, 0, dots, C_TEXT, SUB_SC);
}
