/*
 * uvc_pattern_render() / uvc_pattern_square_x() 宿主机回归测试 + 图案预览。
 *
 * UVC 测试图案的失败模式（色条顺序反了、宽度算错留出一条余数带、方块跑出画面、
 * 灰阶带每帧不变）全都是「host 侧只看得到'图怪怪的'、反推不到哪一行代码」的
 * 那类。所以照 test_standby_screen.c 的做法：不引入任何测试框架，就是
 * main() + assert()，直接编译被测的真实源码（main/uvc_pattern.c），
 * 不是复制粘贴的另一份实现。
 *
 * 编译运行：
 *   cd firmware/test
 *   cc -std=c11 -Wall -Wextra -Werror -I../main test_uvc_pattern.c \
 *       ../main/uvc_pattern.c -o /tmp/test_uvc_pattern && /tmp/test_uvc_pattern
 *
 * 带一个路径参数时另外导出 PPM 预览（macOS 上 `open` 直接能看）：
 *   /tmp/test_uvc_pattern /tmp/pattern.ppm
 * 这张 PPM 正是 jpeg_to_header.py 的输入，也就是 P4 Task5 那张静态测试图 ——
 * 用户在 ffplay 里看到的就是它，所以三个元素都得**一眼可见**。
 *
 * ⚠️ 导出帧号取 PREVIEW_FRAME = 19，不是随手取小数：
 *   · 方块在 x = 16×19 = 304，落在绿色条上，白方块对比鲜明；
 *     取 frame 3 的话方块在 x = 48，整个埋在**白色**色条里，肉眼看不见；
 *   · 灰阶带亮度 = (19×8) & 0xFF = 152，中灰；frame 3 只有 24，几乎全黑，
 *     "灰阶带在不在"根本判断不了。
 *
 * 全部用例通过时打印 "OK (N cases)" 并以 0 退出。
 */
#include "uvc_pattern.h"

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/*
 * 被测尺寸。**必须与 main/usb_descriptors.h 的 UVC_W / UVC_H 一致**，
 * 但这里刻意重写一遍字面量而不是去 include 那个头 —— usb_descriptors.h
 * 第一行就 `#include "tusb.h"`，在宿主机上编不动；而且与 check_usb_desc.py
 * 的 EXPECT 同理，独立重写一遍才有交叉检查的价值。
 * 被测函数本身是尺寸无关的，下面还会用别的尺寸打它的边界。
 */
#define W 640
#define H 360

#define CANARY 0xDEAD   /* 越界写入的哨兵：渲染只许碰画布本身 */
#define GUARD  8        /* 画布前后各留几个哨兵 */
#define SQ     40       /* 与 uvc_pattern.c 的方块边长一致 */
#define BAND   16       /* 与 uvc_pattern.c 的灰阶带高度一致 */
#define STEP   16       /* 与 uvc_pattern.c 的每帧位移一致 */
/* 导出预览用的帧号，选取理由见文件头 ⚠️。 */
#define PREVIEW_FRAME 19

/* 标准彩条，与 uvc_pattern.c 的 k_bars 顺序一致（此处同样刻意重写一遍）。 */
static const uint16_t k_want[UVC_PATTERN_BARS] = {
    0xFFFF, 0xFFE0, 0x07FF, 0x07E0, 0xF81F, 0xF800, 0x001F, 0x0000,
};

static int s_cases;

static void check(const char *name, int cond)
{
    if (!cond) {
        fprintf(stderr, "FAIL [%s]\n", name);
        exit(1);
    }
    s_cases++;
}

/* RGB565 → 24bit，与 uvc_pattern.c 的 rgb565() 互逆（低位补 0） */
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

static void fill_canary(uint16_t *mem, int npx)
{
    for (int i = 0; i < npx + 2 * GUARD; i++)
        mem[i] = CANARY;
}

/* 前后哨兵是否原封不动 */
static int canary_intact(const uint16_t *mem, int npx)
{
    for (int i = 0; i < GUARD; i++)
        if (mem[i] != CANARY || mem[GUARD + npx + i] != CANARY)
            return 0;
    return 1;
}

int main(int argc, char **argv)
{
    const int npx = W * H;
    uint16_t *mem = malloc((size_t)(npx + 2 * GUARD) * sizeof(uint16_t));
    assert(mem);
    uint16_t *fb = mem + GUARD;
    const int bar_w = W / UVC_PATTERN_BARS;

    /* ── 1) 正常渲染不越界写 ── */
    fill_canary(mem, npx);
    check("640×360 渲染成功", uvc_pattern_render(fb, W, H, 3));
    check("渲染未越界写", canary_intact(mem, npx));

    /* ── 2) 拒绝非法参数，且**一个字节都不写**（不是画一半再返回） ── */
    fill_canary(mem, npx);
    check("拒绝 dst == NULL", !uvc_pattern_render(NULL, W, H, 0));
    check("拒绝宽度不被 8 整除", !uvc_pattern_render(fb, 641, H, 0));
    check("拒绝过矮的画布(h=31)", !uvc_pattern_render(fb, W, 31, 0));
    /*
     * ⚠️ 高度下限是 BAND + SQ = 56，**不是 32**：方块高 40 且画在灰阶带之上，
     *    h ∈ [32,55] 会让 sy = (h−BAND−SQ)/2 变成负数，方块那两层循环往
     *    缓冲**前面**写 —— 是越界写，不是画歪。下面两条正是抓这个的。
     */
    check("拒绝装不下方块的高度(h=40)", !uvc_pattern_render(fb, W, 40, 0));
    check("拒绝 h = BAND+SQ-1", !uvc_pattern_render(fb, W, BAND + SQ - 1, 0));
    check("非法参数下缓冲的哨兵完好", canary_intact(mem, npx));
    {
        int untouched = 1;
        for (int i = 0; i < npx; i++)
            untouched &= (fb[i] == CANARY);
        check("非法参数下一个像素都没写", untouched);
    }
    /* 恰好等于下限的那一档必须成功，且不越界 */
    fill_canary(mem, npx);
    check("接受 h = BAND+SQ", uvc_pattern_render(fb, W, BAND + SQ, 0));
    {
        /* 只用了前 W*(BAND+SQ) 个像素，其余仍应是哨兵 */
        int tail_ok = 1;
        for (int i = W * (BAND + SQ); i < npx; i++)
            tail_ok &= (fb[i] == CANARY);
        check("h = BAND+SQ 时只写了自己那几行", tail_ok && canary_intact(mem, npx));
    }

    /* ── 3) 色条：8 根等宽、顺序正确、边界处确实换色 ── */
    fill_canary(mem, npx);
    uvc_pattern_render(fb, W, H, 0);
    /* 第 0 行取每根色条的中点。顺序错 ⇒ R/B 通道搞反了。 */
    for (int i = 0; i < UVC_PATTERN_BARS; i++)
        check("色条颜色与顺序", fb[bar_w / 2 + i * bar_w] == k_want[i]);
    /* 相邻色条的边界两侧必须不同色 —— 宽度算错（留出余数带）时这条会炸 */
    for (int i = 1; i < UVC_PATTERN_BARS; i++)
        check("色条边界确实换色", fb[i * bar_w - 1] != fb[i * bar_w]);
    check("最右一根色条一直画到右边缘", fb[W - 1] == k_want[UVC_PATTERN_BARS - 1]);

    /* ── 4) 灰阶带：最后 BAND 行整块同色，且帧号变了颜色就变 ── */
    {
        const uint16_t c = fb[(H - BAND) * W];
        int uniform = 1;
        for (int y = H - BAND; y < H; y++)
            for (int x = 0; x < W; x++)
                uniform &= (fb[y * W + x] == c);
        check("灰阶带整块同色", uniform);
        check("灰阶带只占最后 BAND 行", fb[(H - BAND - 1) * W] == k_want[0]);

        uint16_t *fb2 = malloc((size_t)npx * sizeof(uint16_t));
        assert(fb2);
        uvc_pattern_render(fb2, W, H, 1);
        check("相邻帧的灰阶带亮度不同（截图能读出帧号）",
              fb2[(H - BAND) * W] != c);
        free(fb2);
    }

    /* ── 5) 方块：永不越界、相邻帧位移恒为 STEP、四角确实是白的 ── */
    {
        int prev = uvc_pattern_square_x(W, 0);
        int seen_min = prev, seen_max = prev;
        for (uint32_t n = 1; n <= 1000; n++) {
            const int x = uvc_pattern_square_x(W, n);
            check("方块左上角落在 [0, w-SQ]", x >= 0 && x <= W - SQ);
            /* 位移必须**恒为** STEP：host 侧才能把「位移 ≠ STEP」直接读成丢帧。
             * uvc_pattern.c 为此把行程取到 STEP 的整数倍，见那里的注释。 */
            const int d = x - prev;
            check("相邻帧位移恒为 STEP", d == STEP || d == -STEP);
            if (x < seen_min)
                seen_min = x;
            if (x > seen_max)
                seen_max = x;
            prev = x;
        }
        check("方块确实走到过最左", seen_min == 0);
        check("方块确实走到过接近最右", seen_max >= W - SQ - STEP);
    }
    {
        const uint32_t frame = 3;
        fill_canary(mem, npx);
        uvc_pattern_render(fb, W, H, frame);
        const int sx = uvc_pattern_square_x(W, frame);
        const int sy = (H - BAND - SQ) / 2;
        check("方块左上角是白的", fb[sy * W + sx] == 0xFFFF);
        check("方块右上角是白的", fb[sy * W + sx + SQ - 1] == 0xFFFF);
        check("方块左下角是白的", fb[(sy + SQ - 1) * W + sx] == 0xFFFF);
        check("方块右下角是白的", fb[(sy + SQ - 1) * W + sx + SQ - 1] == 0xFFFF);
        /* 方块四周应当还是色条色（方块没被画歪、没扩大） */
        check("方块上边缘之上不属于方块",
              fb[(sy - 1) * W + sx] == k_want[sx / bar_w]);
        check("方块下边缘之下不属于方块",
              fb[(sy + SQ) * W + sx] == k_want[sx / bar_w]);
        if (sx > 0)
            check("方块左侧紧邻的像素不属于方块",
                  fb[sy * W + sx - 1] == k_want[(sx - 1) / bar_w]);
    }

    /* ── 6) 确定性：同一帧号渲染两次逐字节相同 ──
     * P4 Task6 会用它做「编码前后帧缓冲没被改写」的对照。 */
    {
        uint16_t *a = malloc((size_t)npx * sizeof(uint16_t));
        uint16_t *b = malloc((size_t)npx * sizeof(uint16_t));
        assert(a && b);
        uvc_pattern_render(a, W, H, 42);
        uvc_pattern_render(b, W, H, 42);
        check("同一帧号渲染两次逐字节相同",
              memcmp(a, b, (size_t)npx * sizeof(uint16_t)) == 0);
        free(a);
        free(b);
    }

    if (argc > 1) {
        fill_canary(mem, npx);
        uvc_pattern_render(fb, W, H, PREVIEW_FRAME);
        write_ppm(argv[1], fb, W, H);
    }

    free(mem);
    printf("OK (%d cases)\n", s_cases);
    return 0;
}
