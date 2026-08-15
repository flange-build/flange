/*
 * standby_render() / standby_render_dots() 宿主机回归测试 + 版式预览。
 *
 * 待机画面的失败模式（文字越界、两行叠在一起、颜色算反、点动画跟副标题脱节）
 * 全都是**看一眼就知道、烧一轮板才能看到**的那类。所以照 test_touch_map.c 的
 * 做法：不引入任何测试框架，就是 main() + assert()，直接编译被测的真实源码
 * （main/standby_screen.c），不是复制粘贴的另一份实现。
 *
 * 编译运行：
 *   cd firmware/test
 *   cc -std=c11 -Wall -Wextra -I../main test_standby_screen.c \
 *       ../main/standby_screen.c -o /tmp/test_standby && /tmp/test_standby
 *
 * 带一个路径参数时另外导出 PPM 预览（macOS 上 `open` 直接能看）：
 *   /tmp/test_standby /tmp/standby.ppm
 *
 * 全部用例通过时打印 "OK (N cases)" 并以 0 退出。
 */
#include "standby_screen.h"
#include "tab5_pins.h"

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CANARY 0xDEAD   /* 越界写入的哨兵：渲染只许碰画布本身 */

static int s_cases;

static void check(const char *name, int cond)
{
    if (!cond) {
        fprintf(stderr, "FAIL [%s]\n", name);
        exit(1);
    }
    s_cases++;
}

/* RGB565 → 24bit，与 standby_screen.c 的 RGB565() 互逆（低位补 0） */
static void unpack(uint16_t c, unsigned char rgb[3])
{
    rgb[0] = (unsigned char)((c >> 11) << 3);
    rgb[1] = (unsigned char)(((c >> 5) & 0x3F) << 2);
    rgb[2] = (unsigned char)((c & 0x1F) << 3);
}

static void write_ppm(const char *path, const uint16_t *px, int w, int h)
{
    FILE *f = fopen(path, "wb");
    if (!f) {
        perror(path);
        exit(1);
    }
    fprintf(f, "P6\n%d %d\n255\n", w, h);
    for (int i = 0; i < w * h; i++) {
        unsigned char rgb[3];
        unpack(px[i], rgb);
        fwrite(rgb, 1, 3, f);
    }
    fclose(f);
    printf("预览已写出: %s (%dx%d)\n", path, w, h);
}

/* 统计缓冲里某颜色的像素数 */
static int count_color(const uint16_t *px, int n, uint16_t color)
{
    int k = 0;
    for (int i = 0; i < n; i++)
        if (px[i] == color)
            k++;
    return k;
}

int main(int argc, char **argv)
{
    const int npx = GUD_W * GUD_H;
    /* 前后各留一段哨兵，渲染写出画布即被抓住 */
    uint16_t *mem = malloc((size_t)(npx + 32) * sizeof(uint16_t));
    assert(mem);
    for (int i = 0; i < npx + 32; i++)
        mem[i] = CANARY;
    uint16_t *fb = mem + 16;

    standby_render(fb);

    int canary_ok = 1;
    for (int i = 0; i < 16; i++)
        canary_ok &= (mem[i] == CANARY) && (mem[16 + npx + i] == CANARY);
    check("整屏渲染未越界写", canary_ok);

    /* 背景色：四角必须是同一个深色，且不是纯黑（要求「不刺眼但不纯黑」） */
    const uint16_t bg = fb[0];
    check("左上=背景", bg != 0x0000);
    check("右上=背景", fb[GUD_W - 1] == bg);
    check("左下=背景", fb[(GUD_H - 1) * GUD_W] == bg);
    check("右下=背景", fb[GUD_H * GUD_W - 1] == bg);

    /* 各元素落在预期的行带里：用「该行带内有非背景像素」判定，
     * 同时要求元素之间的空隙确实是空的（否则就是两行叠了）。 */
    int nonbg_rows[GUD_H];
    memset(nonbg_rows, 0, sizeof(nonbg_rows));
    for (int y = 0; y < GUD_H; y++)
        for (int x = 0; x < GUD_W; x++)
            if (fb[y * GUD_W + x] != bg)
                nonbg_rows[y]++;

    struct { const char *name; int y0, y1; int want; } bands[] = {
        { "顶部留白",        0,   40,  0 },
        { "显示器图标",      40,  132, 1 },
        { "图标与标题之间",  132, 164, 0 },
        { "NO SIGNAL",       164, 212, 1 },
        { "标题与副标题之间", 212, 236, 0 },
        { "Waiting…",        236, 268, 1 },
        { "副标题与分隔线间", 268, 292, 0 },
        { "分隔线",          292, 293, 1 },
        { "脚注 1",          310, 326, 1 },
        { "脚注 2",          330, 346, 1 },
        { "底部留白",        346, 360, 0 },
    };
    for (size_t b = 0; b < sizeof(bands) / sizeof(bands[0]); b++) {
        int sum = 0;
        for (int y = bands[b].y0; y < bands[b].y1; y++)
            sum += nonbg_rows[y];
        check(bands[b].name, bands[b].want ? sum > 0 : sum == 0);
    }

    /* 文字必须离左右边至少 8 px —— 越界钳位会把字沿边切平，肉眼未必看得出 */
    int margin_ok = 1;
    for (int y = 0; y < GUD_H; y++)
        for (int x = 0; x < 8; x++)
            margin_ok &= (fb[y * GUD_W + x] == bg) &&
                         (fb[y * GUD_W + GUD_W - 1 - x] == bg);
    check("左右边距 8px 干净", margin_ok);

    /* 层次：标题与正文必须是两种颜色，否则「状态色」这一层白设计了 */
    uint16_t title_c = bg, sub_c = bg;
    for (int y = 164; y < 212 && title_c == bg; y++)
        for (int x = 0; x < GUD_W && title_c == bg; x++)
            title_c = fb[y * GUD_W + x];
    for (int y = 236; y < 268 && sub_c == bg; y++)
        for (int x = 0; x < GUD_W && sub_c == bg; x++)
            sub_c = fb[y * GUD_W + x];
    check("标题有前景色", title_c != bg);
    check("副标题有前景色", sub_c != bg);
    check("标题色 ≠ 正文色", title_c != sub_c);
    check("标题是最大字号那一档", count_color(fb, npx, title_c) > 500);

    /* 点动画：phase 0 全背景，点数越多前景像素越多，且每一相都不越界 */
    const int dots_px = STANDBY_DOTS_W * STANDBY_DOTS_H;
    uint16_t *dmem = malloc((size_t)(dots_px + 32) * sizeof(uint16_t));
    assert(dmem);
    int prev = -1;
    for (int phase = 0; phase < STANDBY_DOTS_PHASES; phase++) {
        for (int i = 0; i < dots_px + 32; i++)
            dmem[i] = CANARY;
        uint16_t *dots = dmem + 16;
        standby_render_dots(dots, phase);
        int dcanary = 1;
        for (int i = 0; i < 16; i++)
            dcanary &= (dmem[i] == CANARY) && (dmem[16 + dots_px + i] == CANARY);
        check("点动画未越界写", dcanary);
        int fgpx = dots_px - count_color(dots, dots_px, bg);
        check("点动画背景与整屏一致", dots[0] == bg);
        if (phase == 0)
            check("phase 0 无点", fgpx == 0);
        check("点数递增", fgpx > prev);
        prev = fgpx;
    }
    /* 越界的相位钳位到 0..3，不崩也不画出格 */
    standby_render_dots(dmem + 16, 99);
    standby_render_dots(dmem + 16, -1);
    int clamp_ok = 1;
    for (int i = 0; i < 16; i++)
        clamp_ok &= (dmem[i] == CANARY) && (dmem[16 + dots_px + i] == CANARY);
    check("越界相位被钳位，未越界写", clamp_ok);

    if (argc > 1) {
        /* 把点动画的最后一相合成回整屏，导出的预览才是屏上真实的样子 */
        uint16_t *dots = dmem + 16;
        standby_render_dots(dots, 3);
        for (int y = 0; y < STANDBY_DOTS_H; y++)
            memcpy(&fb[(STANDBY_DOTS_Y + y) * GUD_W + STANDBY_DOTS_X],
                   &dots[y * STANDBY_DOTS_W],
                   STANDBY_DOTS_W * sizeof(uint16_t));
        write_ppm(argv[1], fb, GUD_W, GUD_H);
    }

    free(dmem);
    free(mem);
    printf("OK (%d cases)\n", s_cases);
    return 0;
}
