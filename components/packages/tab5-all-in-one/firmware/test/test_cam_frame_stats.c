/*
 * cam_frame_stats_rgb565() 宿主机回归测试。
 *
 * 为什么这个函数值得测：P4 Task8 不接 UVC，「摄像头到底取到画面没有」在现场只剩
 * 日志里的 mean/min/max/checksum 四个数字。这四个数字算错的话，**上板看到的一切
 * 都是假的** —— 全黑缓冲会被念成正常画面，或者反过来把好画面判成坏的。
 * 所以照 test_audio_frame.c 的做法：无框架，main() + assert()，直接编译被测的
 * 真实源码（main/cam_frame_stats.c），不是复制粘贴的另一份实现。
 *
 * 编译运行：
 *   cd firmware/test
 *   cc -std=c11 -Wall -Wextra -Werror -I../main test_cam_frame_stats.c \
 *       ../main/cam_frame_stats.c -o /tmp/test_cam_frame_stats && /tmp/test_cam_frame_stats
 *
 * 全部用例通过时打印 "OK (N cases)" 并以 0 退出。
 */
#include "cam_frame_stats.h"

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int cases;

#define W 32
#define H 16

static uint16_t buf[W * H];

static void fill(uint16_t v)
{
    for (int i = 0; i < W * H; i++) buf[i] = v;
}

static void expect(const char *name, int step, uint32_t samples,
                   uint8_t mean, uint8_t lo, uint8_t hi)
{
    cam_frame_stats_t s;
    cam_frame_stats_rgb565(buf, W, H, step, &s);
    if (s.samples != samples || s.lum_mean != mean || s.lum_min != lo || s.lum_max != hi) {
        fprintf(stderr, "FAIL [%s]: samples=%u mean=%u min=%u max=%u，"
                        "期望 samples=%u mean=%u min=%u max=%u\n",
                name, s.samples, s.lum_mean, s.lum_min, s.lum_max,
                samples, mean, lo, hi);
        assert(0 && "cam_frame_stats 用例失败");
    }
    cases++;
}

static uint32_t sum_of(int step)
{
    cam_frame_stats_t s;
    cam_frame_stats_rgb565(buf, W, H, step, &s);
    return s.checksum;
}

int main(void)
{
    /* ── 两个端点必须是精确的，判读时才不用留余量 ── */
    fill(0x0000);
    expect("全黑", 1, W * H, 0, 0, 0);

    fill(0xFFFF);
    expect("全白", 1, W * H, 255, 255, 255);
    /* 若把 5/6 位分量简单左移扩到 8 位，这里会是 250 而不是 255 —— 那样
     * 「全白」这个判据就带一个说不清的偏差，所以单拎出来钉死。 */

    /* ── 纯色的识别靠 min == max，与「有明暗差」严格区分 ── */
    fill(0x0000);
    for (int y = 0; y < H / 2; y++)
        for (int x = 0; x < W; x++) buf[y * W + x] = 0xFFFF;
    expect("上白下黑", 1, W * H, 127, 0, 255);   /* (255*256 + 0*256)/512 = 127.5 → 127 */

    /* ── 单色通道：权重必须是 BT.601 那三个，不能是「取绿色分量」── */
    fill(0xF800);   /* 纯红 */
    expect("纯红", 1, W * H, (uint8_t)((77u * 255u) >> 8), (uint8_t)((77u * 255u) >> 8),
           (uint8_t)((77u * 255u) >> 8));
    fill(0x07E0);   /* 纯绿 */
    expect("纯绿", 1, W * H, (uint8_t)((150u * 255u) >> 8), (uint8_t)((150u * 255u) >> 8),
           (uint8_t)((150u * 255u) >> 8));
    fill(0x001F);   /* 纯蓝 */
    expect("纯蓝", 1, W * H, (uint8_t)((29u * 255u) >> 8), (uint8_t)((29u * 255u) >> 8),
           (uint8_t)((29u * 255u) >> 8));

    /* ── 采样步长：只能看被采到的那些像素 ──
     * 把「会被采到」的像素涂黑、其余涂白。step=8 时结果必须是全黑；
     * 若步长算错（比如把 x 的步长写成 1），立刻变成有黑有白。 */
    fill(0xFFFF);
    for (int y = 0; y < H; y += 8)
        for (int x = 0; x < W; x += 8) buf[y * W + x] = 0x0000;
    expect("步长 8 只采到黑点", 8, (uint32_t)((H + 7) / 8) * (uint32_t)((W + 7) / 8), 0, 0, 0);
    /* 同一块数据全采样时必然是「白为主、有黑点」，反证上面那条不是碰巧全黑 */
    /* 512 个像素里有 2 行 × 4 列 = 8 个黑点 ⇒ (504×255)/512 = 251 */
    expect("同数据全采样有黑有白", 1, W * H, 251, 0, 255);

    /* ── checksum：位置敏感，且相同输入必然相同 ── */
    {
        fill(0x0000);
        buf[0] = 0x1234;
        const uint32_t a = sum_of(1);
        fill(0x0000);
        buf[0] = 0x1234;
        assert(sum_of(1) == a);          /* 同样的帧 ⇒ 同样的散列 */
        cases++;

        fill(0x0000);
        buf[1] = 0x1234;                 /* 同一个值换个位置 */
        if (sum_of(1) == a) {
            fprintf(stderr, "FAIL [checksum]: 像素换位置后散列没变，"
                            "无法判断画面动没动\n");
            assert(0 && "checksum 不是位置敏感的");
        }
        cases++;

        fill(0x0000);
        buf[0] = 0x1235;                 /* 同一位置换个值 */
        if (sum_of(1) == a) {
            fprintf(stderr, "FAIL [checksum]: 像素值变了散列没变\n");
            assert(0 && "checksum 对像素值不敏感");
        }
        cases++;
    }

    /* ── 参数非法：samples == 0 是唯一的「什么都没统计到」表达 ──
     * 它必须与「统计到了，结果全是 0（纯黑）」长得不一样 —— 全黑那条用例里
     * samples == W*H，正是这里要区分开的东西。 */
    {
        cam_frame_stats_t s;
        const cam_frame_stats_t zero = {0, 0, 0, 0, 0};

        cam_frame_stats_rgb565(NULL, W, H, 1, &s);
        assert(memcmp(&s, &zero, sizeof(s)) == 0);
        cam_frame_stats_rgb565(buf, 0, H, 1, &s);
        assert(memcmp(&s, &zero, sizeof(s)) == 0);
        cam_frame_stats_rgb565(buf, W, 0, 1, &s);
        assert(memcmp(&s, &zero, sizeof(s)) == 0);
        cam_frame_stats_rgb565(buf, W, H, 0, &s);
        assert(memcmp(&s, &zero, sizeof(s)) == 0);
        cam_frame_stats_rgb565(buf, W, H, -1, &s);
        assert(memcmp(&s, &zero, sizeof(s)) == 0);
        cam_frame_stats_rgb565(buf, W, H, 1, NULL);   /* 不许崩 */
        cases += 6;
    }

    /* ── 步长大于图像：至少采到左上角那一个像素，不能除零 ── */
    fill(0xFFFF);
    expect("步长大于整幅图", 1000, 1, 255, 255, 255);

    printf("OK (%d cases)\n", cases);
    return 0;
}
