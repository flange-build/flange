/*
 * audio_frame_mono_to_stereo() / audio_frame_stereo_to_mono() 宿主机回归测试。
 *
 * 这两个函数是 USB 单声道与 I2S 线上立体声之间唯一的翻译层，写错了在实机上只
 * 表现为「声音小一半 / 只有一边有声 / 音高快一倍」—— 从现象几乎反推不出是哪一步
 * 算错，而这块板现场没有串口可查。所以照 test_touch_map.c 的做法：不引入任何测试
 * 框架，就是 main() + assert()，直接编译被测的真实源码（main/audio_frame.c），
 * 不是复制粘贴的另一份实现。
 *
 * 编译运行：
 *   cd firmware/test
 *   cc -std=c11 -Wall -Wextra -I../main test_audio_frame.c ../main/audio_frame.c \
 *       -o /tmp/test_audio_frame && /tmp/test_audio_frame
 *
 * 全部用例通过时打印 "OK (N cases)" 并以 0 退出。
 */
#include "audio_frame.h"

#include <assert.h>
#include <stdio.h>

static int cases;

static void expect_m2s(const char *name, const int16_t *mono, size_t frames,
                       const int16_t *want)
{
    /* 前后各留一个哨兵：越界写会被抓住，而不是等到实机上表现成杂音。 */
    int16_t buf[2 + 2 * 4 + 2] = {0x5A5A, 0x5A5A};
    int16_t *stereo = buf + 2;

    for (size_t i = 0; i < 2 * 4 + 2; i++) buf[2 + i] = 0x5A5A;
    audio_frame_mono_to_stereo(mono, stereo, frames);

    assert(buf[0] == 0x5A5A && buf[1] == 0x5A5A);
    for (size_t i = 0; i < 2 * frames; i++) {
        if (stereo[i] != want[i]) {
            fprintf(stderr, "FAIL [%s]: stereo[%zu] = %d, want %d\n",
                    name, i, stereo[i], want[i]);
            assert(0 && "mono_to_stereo 用例失败");
        }
    }
    /* 越过 frames 的部分必须原封不动 */
    for (size_t i = 2 * frames; i < 2 * 4 + 2; i++) {
        if (buf[2 + i] != 0x5A5A) {
            fprintf(stderr, "FAIL [%s]: 写越界到 stereo[%zu]\n", name, i);
            assert(0 && "mono_to_stereo 写越界");
        }
    }
    cases++;
}

static void expect_s2m(const char *name, int16_t l, int16_t r, int16_t want)
{
    const int16_t stereo[2] = {l, r};
    int16_t mono[2] = {0x5A5A, 0x5A5A};   /* 第二个是哨兵 */

    audio_frame_stereo_to_mono(stereo, mono, 1);
    if (mono[0] != want || mono[1] != 0x5A5A) {
        fprintf(stderr, "FAIL [%s]: (%d,%d) -> %d, want %d (哨兵 %d)\n",
                name, l, r, mono[0], want, mono[1]);
        assert(0 && "stereo_to_mono 用例失败");
    }
    cases++;
}

int main(void)
{
    /* ── mono → stereo：左右两路都等于源 ── */
    const int16_t m3[3] = {100, -200, 32767};
    const int16_t w3[6] = {100, 100, -200, -200, 32767, 32767};
    expect_m2s("三帧", m3, 3, w3);

    /* frames == 0 时一个字节都不该写 */
    expect_m2s("零帧", m3, 0, w3);

    /* ── stereo → mono：算术平均 ── */
    expect_s2m("正数", 100, 200, 150);
    expect_s2m("负数", -100, -200, -150);      /* (-300) >> 1 == -150 */
    expect_s2m("同值", 1234, 1234, 1234);
    expect_s2m("正负抵消", 500, -500, 0);

    /*
     * 右移与 /2 唯一会分叉的那一类，必须钉死：右移向下取整，除法向零取整。
     * 日后有人「顺手改成 /2」听不出差别，但行为变了。
     */
    expect_s2m("右移向下取整(1,0)", 1, 0, 0);
    expect_s2m("右移向下取整(-1,0)", -1, 0, -1);   /* (-1)>>1 == -1，而 (-1)/2 == 0 */
    expect_s2m("右移向下取整(-3,0)", -3, 0, -2);   /* (-3)>>1 == -2，而 (-3)/2 == -1 */

    /* 满量程不溢出：int32 中间量那条注释要防的就是这个 */
    expect_s2m("正满量程", 32767, 32767, 32767);
    expect_s2m("负满量程", -32768, -32768, -32768);
    expect_s2m("异号满量程", 32767, -32768, -1);   /* (-1)>>1 == -1 */

    /* ── 往返一致性：左右同值时平均即原值 ── */
    {
        const int16_t src[4] = {0, -32768, 32767, 12345};
        int16_t stereo[8];
        int16_t back[4];

        audio_frame_mono_to_stereo(src, stereo, 4);
        audio_frame_stereo_to_mono(stereo, back, 4);
        for (size_t i = 0; i < 4; i++) {
            if (back[i] != src[i]) {
                fprintf(stderr, "FAIL [往返]: back[%zu] = %d, want %d\n",
                        i, back[i], src[i]);
                assert(0 && "mono→stereo→mono 不是恒等");
            }
        }
        cases++;
    }

    printf("OK (%d cases)\n", cases);
    return 0;
}
