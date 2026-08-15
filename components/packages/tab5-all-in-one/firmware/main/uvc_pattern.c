#include "uvc_pattern.h"

#define SQ   40      /* 方块边长 */
#define BAND 16      /* 底部灰阶带高度 */
#define STEP 16      /* 方块每帧移动的像素数：10 fps 下约 1.6 s 扫完 640 宽 */

/* RGB565 小端。与 display_dsi.c 的取用方式一致（BSP_LCD_BIGENDIAN=0），
 * 这里不做任何 byteswap —— 硬件 JPEG 编码器的 RGB565 输入也是小端。 */
static inline uint16_t rgb565(int r, int g, int b)
{
    return (uint16_t)(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | ((b & 0xF8) >> 3));
}

/* 标准彩条顺序（白→黄→青→绿→品红→红→蓝→黑）。顺序反了 ⇒ R/B 通道搞反。 */
static const uint16_t k_bars[UVC_PATTERN_BARS] = {
    0xFFFF,                    /* 白   */
    0xFFE0,                    /* 黄   R+G  */
    0x07FF,                    /* 青   G+B  */
    0x07E0,                    /* 绿   */
    0xF81F,                    /* 品红 R+B  */
    0xF800,                    /* 红   */
    0x001F,                    /* 蓝   */
    0x0000,                    /* 黑   */
};

int uvc_pattern_square_x(int w, uint32_t frame_no)
{
    /*
     * 行程取「不超过 w−SQ 的最大 STEP 整数倍」，而不是直接用 w−SQ。
     *
     * 理由是这个函数的**唯一诊断价值**：相邻两帧的位移必须恒等于 STEP，
     * host 侧才能把「位移 ≠ STEP」直接读成丢帧。若行程不是 STEP 的整数倍
     * （640−40 = 600 不是 16 的倍数），三角波在折返点附近会出现一次
     * Δ=0 的「停顿帧」—— 那是算法本身造成的，却与真正的丢帧长得一模一样，
     * 等于亲手往诊断信号里掺噪声。代价是少走几个像素（640 下是 592 而非 600）。
     */
    const int span = (w - SQ) / STEP * STEP;   /* 方块左上角的合法范围 [0, span] */
    if (span <= 0)
        return 0;
    /* 三角波：先右后左，永远不越界，也不会有"跳回原点"的突变（那会被误判成丢帧）。 */
    const uint32_t period = (uint32_t)(2 * span);
    const uint32_t t = (frame_no * (uint32_t)STEP) % period;
    return (int)(t < (uint32_t)span ? t : period - t);
}

bool uvc_pattern_render(uint16_t *dst, int w, int h, uint32_t frame_no)
{
    /*
     * ⚠️ 高度下限是 **BAND + SQ**，不是 32：方块高 SQ=40 且要画在灰阶带**之上**，
     *    band_y = h − BAND 必须 ≥ SQ 才有它的位置。写成 32 的话 h ∈ [32, 55]
     *    会算出负的 sy，方块那两层循环直接往缓冲**前面**写 —— 是越界写，
     *    不是画歪。本工程只用 640×360，但这个函数是纯函数、会被测试拿各种
     *    尺寸调，下限必须自洽。
     */
    if (!dst || w <= 0 || h < BAND + SQ || (w % UVC_PATTERN_BARS) != 0)
        return false;

    const int bar_w = w / UVC_PATTERN_BARS;
    const int band_y = h - BAND;
    /* 灰阶带：每帧 +8，32 帧一循环。截图读亮度即可反推帧号。 */
    const int level = (int)((frame_no * 8u) & 0xFFu);
    const uint16_t band = rgb565(level, level, level);

    for (int y = 0; y < band_y; y++) {
        uint16_t *row = dst + (size_t)y * (size_t)w;
        for (int x = 0; x < w; x++)
            row[x] = k_bars[x / bar_w];
    }
    for (int y = band_y; y < h; y++) {
        uint16_t *row = dst + (size_t)y * (size_t)w;
        for (int x = 0; x < w; x++)
            row[x] = band;
    }

    /* 方块画在色条之上、灰阶带之上，纵向居中于色条区。 */
    const int sx = uvc_pattern_square_x(w, frame_no);
    const int sy = (band_y - SQ) / 2;
    for (int y = sy; y < sy + SQ; y++) {
        uint16_t *row = dst + (size_t)y * (size_t)w;
        for (int x = sx; x < sx + SQ; x++)
            row[x] = 0xFFFF;
    }
    return true;
}
