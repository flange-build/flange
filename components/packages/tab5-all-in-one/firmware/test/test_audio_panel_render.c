/*
 * audio_panel_render_status() / _meter() / audio_panel_bar_len() 宿主机回归测试
 * + 版式预览。
 *
 * 这块面板的存在理由是"这块板没有串口，屏幕是唯一看得见的输出"（见 P3 计划的
 * 硬约束 C）。也正因如此，它自己的失败模式没有任何别的观测手段：条画得偏长、
 * 数字被条压住、两行叠在一起、越界写到相邻缓冲——上板只能看出"不对"，看不出
 * "哪里不对"。所以照 test_standby_screen.c 的做法：不引入测试框架，就是
 * main() + assert()，直接编译被测的真实源码，不是复制粘贴的另一份实现。
 *
 * 编译运行：
 *   cd firmware/test
 *   cc -std=c11 -Wall -Wextra -Werror -I../main test_audio_panel_render.c \
 *      ../main/audio_panel_render.c ../main/standby_screen.c -o /tmp/tap && /tmp/tap
 *
 * 带一个路径参数时另外导出 PPM 预览（待机画面 + 面板合成，即屏上真实的样子）：
 *   /tmp/tap /tmp/panel.ppm
 *
 * 全部用例通过时打印 "OK (N cases)" 并以 0 退出。
 */
#include "audio_panel_render.h"
#include "standby_screen.h"
#include "tab5_pins.h"

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CANARY 0xDEAD   /* 越界写入的哨兵：渲染只许碰画布本身 */
#define GUARD  16       /* 画布前后各留这么多个哨兵像素 */

/* 与 audio_panel_render.c 的行内版式一致；测试独立算一遍，
 * 改了那边这边就该炸 —— 这正是"另一份实现"在这里的用处。 */
#define BAR_X   16
#define BAR_Y   3
#define BAR_H   10
#define ROW_H   16

static int s_cases;

static void check(const char *name, int cond)
{
    if (!cond) {
        fprintf(stderr, "FAIL [%s]\n", name);
        exit(1);
    }
    s_cases++;
}

/* RGB565 → 24bit，与 STANDBY_RGB565() 互逆（低位补 0） */
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

/* 带哨兵的画布：返回可写起点，越界写入会破坏前后的哨兵 */
static uint16_t *alloc_canvas(int npx)
{
    uint16_t *mem = malloc((size_t)(npx + 2 * GUARD) * sizeof(uint16_t));
    assert(mem);
    for (int i = 0; i < npx + 2 * GUARD; i++)
        mem[i] = CANARY;
    return mem;
}

static int canary_intact(const uint16_t *mem, int npx)
{
    int ok = 1;
    for (int i = 0; i < GUARD; i++)
        ok &= (mem[i] == CANARY) && (mem[GUARD + npx + i] == CANARY);
    return ok;
}

static int count_color(const uint16_t *px, int n, uint16_t color)
{
    int k = 0;
    for (int i = 0; i < n; i++)
        if (px[i] == color)
            k++;
    return k;
}

/* 某矩形内非 bg 的像素数 */
static int nonbg_in_rect(const uint16_t *px, int stride, uint16_t bg,
                         int x, int y, int w, int h)
{
    int k = 0;
    for (int yy = y; yy < y + h; yy++)
        for (int xx = x; xx < x + w; xx++)
            if (px[yy * stride + xx] != bg)
                k++;
    return k;
}

/* 两个矩形是否相交 */
static int rects_overlap(int ax, int ay, int aw, int ah,
                         int bx, int by, int bw, int bh)
{
    return ax < bx + bw && bx < ax + aw && ay < by + bh && by < ay + ah;
}

static void test_bar_len(void)
{
    check("bar_len(0) = 0", audio_panel_bar_len(0) == 0);
    check("bar_len(满刻度) = BAR_W",
          audio_panel_bar_len(AUDIO_PANEL_PEAK_FULL) == AUDIO_PANEL_BAR_W);

    const int half = audio_panel_bar_len(AUDIO_PANEL_PEAK_FULL / 2);
    check("bar_len(半刻度) ≈ BAR_W/2",
          half >= AUDIO_PANEL_BAR_W / 2 - 1 && half <= AUDIO_PANEL_BAR_W / 2 + 1);

    /* 超过满刻度必须钳位而不是绕回。uint32_t 中间量那条注释防的就是这个：
     * 若中间量用了 uint16_t，65535×140 会溢出成一个很小的数，条反而变短。 */
    check("bar_len(满刻度+1) 钳位",
          audio_panel_bar_len(AUDIO_PANEL_PEAK_FULL + 1) == AUDIO_PANEL_BAR_W);
    check("bar_len(0xFFFF) 钳位", audio_panel_bar_len(0xFFFF) == AUDIO_PANEL_BAR_W);

    /* 单调不减：任何一段"条变短了但声音变大了"都是错的 */
    int mono = 1;
    uint16_t prev = 0;
    for (uint32_t p = 0; p <= AUDIO_PANEL_PEAK_FULL; p += 128) {
        uint16_t len = audio_panel_bar_len((uint16_t)p);
        mono &= (len >= prev) && (len <= AUDIO_PANEL_BAR_W);
        prev = len;
    }
    check("bar_len 单调不减且不超 BAR_W", mono);
}

static void test_status(uint16_t bg)
{
    const int npx = AUDIO_PANEL_STATUS_W * AUDIO_PANEL_STATUS_H;
    uint16_t *mem = alloc_canvas(npx);
    uint16_t *buf = mem + GUARD;

    /* 三行正常文本 */
    const char *l3[] = { "I2C  ES8388 OK   ES7210 OK",
                         "I2S  16000Hz 16bit 2slot  duplex=1",
                         "ES8388 OK  vol=70  PA=on" };
    audio_panel_render_status(buf, l3, 3);
    check("状态区渲染未越界写", canary_intact(mem, npx));
    check("状态区背景是面板背景色", buf[0] == bg);
    for (int i = 0; i < AUDIO_PANEL_STATUS_LINES; i++)
        check("每行都有前景像素",
              nonbg_in_rect(buf, AUDIO_PANEL_STATUS_W, bg,
                            0, i * 16, AUDIO_PANEL_STATUS_W, 16) > 0);
    /* 底衬那 4 px 纯粹用来盖待机脚注，文本不许侵占它 */
    check("状态区底衬是纯背景",
          nonbg_in_rect(buf, AUDIO_PANEL_STATUS_W, bg,
                        0, AUDIO_PANEL_STATUS_LINES * 16,
                        AUDIO_PANEL_STATUS_W, AUDIO_PANEL_STATUS_PAD) == 0);

    /* NULL 行画成纯背景，且不影响别的行 */
    const char *lnull[] = { "line0", NULL, "line2" };
    audio_panel_render_status(buf, lnull, 3);
    check("NULL 行是纯背景",
          nonbg_in_rect(buf, AUDIO_PANEL_STATUS_W, bg, 0, 16, AUDIO_PANEL_STATUS_W, 16) == 0);
    check("NULL 行不影响第 0 行",
          nonbg_in_rect(buf, AUDIO_PANEL_STATUS_W, bg, 0, 0, AUDIO_PANEL_STATUS_W, 16) > 0);
    check("NULL 行不影响第 2 行",
          nonbg_in_rect(buf, AUDIO_PANEL_STATUS_W, bg, 0, 32, AUDIO_PANEL_STATUS_W, 16) > 0);

    /* 空串同样是纯背景（与 NULL 等价） */
    const char *lempty[] = { "", "", "" };
    audio_panel_render_status(buf, lempty, 3);
    check("空串三行 = 全背景", count_color(buf, npx, bg) == npx);
    check("空串未越界写", canary_intact(mem, npx));

    /* 超长字符串：截断而不越界。128 个 'W'（最宽的字形之一），远超 64 列 */
    char longline[129];
    memset(longline, 'W', sizeof(longline) - 1);
    longline[sizeof(longline) - 1] = '\0';
    const char *llong[] = { longline, NULL, NULL };
    audio_panel_render_status(buf, llong, 3);
    check("超长行未越界写", canary_intact(mem, npx));
    check("超长行填满第 0 行",
          nonbg_in_rect(buf, AUDIO_PANEL_STATUS_W, bg, 0, 0, AUDIO_PANEL_STATUS_W, 16) > 0);
    check("超长行没有溢到第 1 行（截断而不是换行）",
          nonbg_in_rect(buf, AUDIO_PANEL_STATUS_W, bg, 0, 16, AUDIO_PANEL_STATUS_W, 32) == 0);

    /* n 超过行数：按上限截断，不越界 */
    const char *l5[] = { "a", "b", "c", "d", "e" };
    audio_panel_render_status(buf, l5, 5);
    check("n > LINES 被截断且未越界写", canary_intact(mem, npx));

    /* n = 0：全背景 */
    audio_panel_render_status(buf, l3, 0);
    check("n = 0 → 全背景", count_color(buf, npx, bg) == npx);

    free(mem);
}

static void test_meter(uint16_t bg)
{
    const int npx = AUDIO_PANEL_METER_W * AUDIO_PANEL_METER_H;
    const int stride = AUDIO_PANEL_METER_W;
    uint16_t *mem = alloc_canvas(npx);
    uint16_t *buf = mem + GUARD;

    /* 两路零峰值：条区域必须全是背景（不画空槽，否则"静音"看不出来） */
    audio_panel_render_meter(buf, 0, 0);
    check("电平条渲染未越界写", canary_intact(mem, npx));
    check("零峰值时 L 条区域全背景",
          nonbg_in_rect(buf, stride, bg, BAR_X, BAR_Y, AUDIO_PANEL_BAR_W, BAR_H) == 0);
    check("零峰值时 R 条区域全背景",
          nonbg_in_rect(buf, stride, bg, BAR_X, ROW_H + BAR_Y, AUDIO_PANEL_BAR_W, BAR_H) == 0);
    check("零峰值仍有标签与数字",
          nonbg_in_rect(buf, stride, bg, 0, 0, stride, AUDIO_PANEL_METER_H) > 0);

    /* 两路不同峰值 → 条长不同，且不互相侵占 */
    audio_panel_render_meter(buf, AUDIO_PANEL_PEAK_FULL, AUDIO_PANEL_PEAK_FULL / 4);
    check("不同峰值未越界写", canary_intact(mem, npx));
    const int lbar = nonbg_in_rect(buf, stride, bg, BAR_X, BAR_Y, AUDIO_PANEL_BAR_W, BAR_H);
    const int rbar = nonbg_in_rect(buf, stride, bg, BAR_X, ROW_H + BAR_Y,
                                   AUDIO_PANEL_BAR_W, BAR_H);
    check("满格 L 条铺满", lbar == AUDIO_PANEL_BAR_W * BAR_H);
    check("1/4 格 R 条明显更短", rbar > 0 && rbar < lbar / 2);

    /* 行带占用：第 0 行的条不许伸进第 1 行，反之亦然 */
    audio_panel_render_meter(buf, AUDIO_PANEL_PEAK_FULL, 0);
    check("L 满格时 R 条区域仍是背景",
          nonbg_in_rect(buf, stride, bg, BAR_X, ROW_H + BAR_Y, AUDIO_PANEL_BAR_W, BAR_H) == 0);
    audio_panel_render_meter(buf, 0, AUDIO_PANEL_PEAK_FULL);
    check("R 满格时 L 条区域仍是背景",
          nonbg_in_rect(buf, stride, bg, BAR_X, BAR_Y, AUDIO_PANEL_BAR_W, BAR_H) == 0);

    /* 溢出峰值：钳位到满格，不绕回、不越界 */
    audio_panel_render_meter(buf, 0xFFFF, 0xFFFF);
    check("溢出峰值未越界写", canary_intact(mem, npx));
    check("溢出峰值 L 条满格",
          nonbg_in_rect(buf, stride, bg, BAR_X, BAR_Y, AUDIO_PANEL_BAR_W, BAR_H)
          == AUDIO_PANEL_BAR_W * BAR_H);

    free(mem);
}

/*
 * 版式关系。与 audio_panel_render.c 里的 _Static_assert 重复是故意的：
 * 断言防编译期，本用例防有人把断言删了。
 */
static void test_layout(void)
{
    check("状态区与电平条不重叠",
          !rects_overlap(AUDIO_PANEL_X, AUDIO_PANEL_Y,
                         AUDIO_PANEL_STATUS_W, AUDIO_PANEL_STATUS_H,
                         AUDIO_PANEL_METER_X, AUDIO_PANEL_METER_Y,
                         AUDIO_PANEL_METER_W, AUDIO_PANEL_METER_H));
    check("状态区不压待机等待点",
          !rects_overlap(AUDIO_PANEL_X, AUDIO_PANEL_Y,
                         AUDIO_PANEL_STATUS_W, AUDIO_PANEL_STATUS_H,
                         STANDBY_DOTS_X, STANDBY_DOTS_Y,
                         STANDBY_DOTS_W, STANDBY_DOTS_H));
    check("电平条不压待机等待点",
          !rects_overlap(AUDIO_PANEL_METER_X, AUDIO_PANEL_METER_Y,
                         AUDIO_PANEL_METER_W, AUDIO_PANEL_METER_H,
                         STANDBY_DOTS_X, STANDBY_DOTS_Y,
                         STANDBY_DOTS_W, STANDBY_DOTS_H));
    check("状态区在画内",
          AUDIO_PANEL_X >= 0 && AUDIO_PANEL_X + AUDIO_PANEL_STATUS_W <= GUD_W &&
          AUDIO_PANEL_Y >= 0 && AUDIO_PANEL_Y + AUDIO_PANEL_STATUS_H <= GUD_H);
    check("电平条在画内",
          AUDIO_PANEL_METER_X >= 0 && AUDIO_PANEL_METER_X + AUDIO_PANEL_METER_W <= GUD_W &&
          AUDIO_PANEL_METER_Y >= 0 && AUDIO_PANEL_METER_Y + AUDIO_PANEL_METER_H <= GUD_H);
    check("状态区宽度正好是整数列", AUDIO_PANEL_STATUS_W == AUDIO_PANEL_COLS * 8);
    check("两块同宽", AUDIO_PANEL_STATUS_W == AUDIO_PANEL_METER_W);
    check("两块紧邻无缝", AUDIO_PANEL_METER_Y == AUDIO_PANEL_Y + AUDIO_PANEL_STATUS_H);
    check("面板盖到画布下边缘", AUDIO_PANEL_METER_Y + AUDIO_PANEL_METER_H == GUD_H);
}

/*
 * 覆盖完整性：面板落笔之后，待机画面在那一带不许留下任何残片。
 *
 * 这是 Task 0 最容易出的"观测工具自己产生误导"——分隔线露半截、脚注露个尾巴，
 * 看上去就是显示坏了。判据不看面板画了什么（那是上面几组用例的事），只看
 * **待机画面本身**在面板脚印之外的那一圈是否干净：
 *   ① 面板上沿之上、等待点之下的那条带（y 268..276）必须是纯背景；
 *   ② 面板脚印所在的行（y 276..360）里，脚印左右两侧必须是纯背景。
 * 这两条成立，面板画上去之后就不可能有残片 —— 与坐标怎么改无关。
 */
static void test_coverage(void)
{
    uint16_t *fb = malloc((size_t)GUD_W * GUD_H * sizeof(uint16_t));
    assert(fb);
    standby_render(fb);
    const uint16_t bg = fb[0];

    int gap_clean = 1;
    for (int y = STANDBY_DOTS_Y + STANDBY_DOTS_H; y < AUDIO_PANEL_Y; y++)
        for (int x = 0; x < GUD_W; x++)
            gap_clean &= (fb[y * GUD_W + x] == bg);
    check("面板上沿与等待点之间没有待机内容", gap_clean);

    int side_clean = 1;
    for (int y = AUDIO_PANEL_Y; y < GUD_H; y++)
        for (int x = 0; x < GUD_W; x++) {
            if (x >= AUDIO_PANEL_X && x < AUDIO_PANEL_X + AUDIO_PANEL_W)
                continue;   /* 脚印内，画上去就没了 */
            side_clean &= (fb[y * GUD_W + x] == bg);
        }
    check("面板脚印左右两侧没有待机内容（分隔线/脚注全在脚印内）", side_clean);

    free(fb);
}

/* 把待机画面 + 面板合成成一张 640×360，导出即屏上真实的样子 */
static void preview(const char *path)
{
    uint16_t *fb = malloc((size_t)GUD_W * GUD_H * sizeof(uint16_t));
    uint16_t *status = malloc((size_t)AUDIO_PANEL_STATUS_W * AUDIO_PANEL_STATUS_H
                              * sizeof(uint16_t));
    uint16_t *meter = malloc((size_t)AUDIO_PANEL_METER_W * AUDIO_PANEL_METER_H
                             * sizeof(uint16_t));
    const char *lines[] = { "I2C  ES8388 OK   ES7210 OK",
                            "I2S  16000Hz 16bit 2slot  duplex=1",
                            "ES8388 OK  vol=70  PA=on" };
    assert(fb && status && meter);

    standby_render(fb);
    audio_panel_render_status(status, lines, 3);
    audio_panel_render_meter(meter, 24576, 8192);

    for (int y = 0; y < AUDIO_PANEL_STATUS_H; y++)
        memcpy(&fb[(AUDIO_PANEL_Y + y) * GUD_W + AUDIO_PANEL_X],
               &status[y * AUDIO_PANEL_STATUS_W],
               AUDIO_PANEL_STATUS_W * sizeof(uint16_t));
    for (int y = 0; y < AUDIO_PANEL_METER_H; y++)
        memcpy(&fb[(AUDIO_PANEL_METER_Y + y) * GUD_W + AUDIO_PANEL_METER_X],
               &meter[y * AUDIO_PANEL_METER_W],
               AUDIO_PANEL_METER_W * sizeof(uint16_t));

    write_ppm(path, fb, GUD_W, GUD_H);
    free(meter);
    free(status);
    free(fb);
}

int main(int argc, char **argv)
{
    /* 面板背景色不写死在测试里：渲染一块全空的状态区，左上角那个像素就是它。
     * 这样调色时测试不用跟着改，而"背景到底是哪个值"仍然只有一个来源。 */
    uint16_t probe[AUDIO_PANEL_STATUS_W * AUDIO_PANEL_STATUS_H];
    const char *none[] = { NULL, NULL, NULL };
    audio_panel_render_status(probe, none, 3);
    const uint16_t bg = probe[0];

    test_bar_len();
    test_status(bg);
    test_meter(bg);
    test_layout();
    test_coverage();

    if (argc > 1)
        preview(argv[1]);

    printf("OK (%d cases)\n", s_cases);
    return 0;
}
