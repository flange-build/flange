/*
 * RGB565 帧内容统计。设计意图与判读方式见 cam_frame_stats.h。
 * 纯逻辑，不含任何 ESP-IDF 依赖 —— 宿主机上 cc 一下就能跑。
 */
#include "cam_frame_stats.h"
#include <string.h>

/* RGB565 → 8 位分量。高位复制到低位，保证满量程映射到 255（31→255、63→255）。 */
static inline uint32_t r8_of(uint16_t p) { uint32_t v = (p >> 11) & 0x1fu; return (v << 3) | (v >> 2); }
static inline uint32_t g8_of(uint16_t p) { uint32_t v = (p >>  5) & 0x3fu; return (v << 2) | (v >> 4); }
static inline uint32_t b8_of(uint16_t p) { uint32_t v =  p        & 0x1fu; return (v << 3) | (v >> 2); }

void cam_frame_stats_rgb565(const uint16_t *fb, int w, int h, int step,
                            cam_frame_stats_t *out)
{
    if (!out)
        return;
    memset(out, 0, sizeof(*out));
    if (!fb || w <= 0 || h <= 0 || step <= 0)
        return;

    /* FNV-1a 32 位。选它的理由只有一个：**逐字节顺序敏感**，
     * 两帧只要有一个采样像素不同、或同样的像素换了位置，散列就变 ——
     * 而「帧与帧之间到底变没变」正是要判的那件事。累加和做不到（换位置不变）。 */
    uint32_t hash = 2166136261u;
    uint32_t sum = 0, n = 0;
    uint32_t lo = 255, hi = 0;
    /* 分通道累加和。采样上限 1280×720 = 921 600 个像素 × 255 = 2.35e8，
     * 离 uint32 的 4.29e9 还有一个量级，全采样也不会溢出。 */
    uint32_t sum_r = 0, sum_g = 0, sum_b = 0;

    for (int y = 0; y < h; y += step) {
        const uint16_t *row = fb + (size_t)y * (size_t)w;
        for (int x = 0; x < w; x += step) {
            const uint16_t p = row[x];
            const uint32_t r = r8_of(p), g = g8_of(p), b = b8_of(p);
            const uint32_t lum = (77u * r + 150u * g + 29u * b) >> 8;
            sum += lum;
            sum_r += r;
            sum_g += g;
            sum_b += b;
            if (lum < lo) lo = lum;
            if (lum > hi) hi = lum;
            hash = (hash ^ (uint32_t)(p & 0xffu)) * 16777619u;
            hash = (hash ^ (uint32_t)(p >> 8))    * 16777619u;
            n++;
        }
    }

    out->samples  = n;
    out->lum_mean = (uint8_t)(sum / n);   /* w、h、step 都 > 0 ⇒ n 至少为 1 */
    out->lum_min  = (uint8_t)lo;
    out->lum_max  = (uint8_t)hi;
    out->checksum = hash;
    out->r_mean   = (uint8_t)(sum_r / n);
    out->g_mean   = (uint8_t)(sum_g / n);
    out->b_mean   = (uint8_t)(sum_b / n);
}
