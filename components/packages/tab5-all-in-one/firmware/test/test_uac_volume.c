/*
 * uac_volume.c 宿主机回归测试。
 *
 * 这是整个「播放音量控制」里最容易错、且实机上最难归因的一段：UAC1 用的是
 * **有符号 1/256 dB**，esp_codec_dev 用的是 **0..100 百分比**，两套刻度的单位、
 * 符号、零点全不一样。换算写错的表现是「音量条能拖但声音不跟着变」「拖到一半
 * 突然静音」「方向反了」—— 全都长得像 codec 或 I2C 出了问题，而这块板现场没有
 * 串口可查（除非开 CONFIG_AIO_DEBUG_CDC）。
 *
 * 照 test_touch_map.c / test_audio_frame.c 的做法：不引入任何测试框架，就是
 * main() + assert()，直接编译被测的真实源码（main/uac_volume.c），不是复制粘贴
 * 的另一份实现。
 *
 * 编译运行：
 *   cd firmware/test
 *   cc -std=c11 -Wall -Wextra -Werror -I../main test_uac_volume.c ../main/uac_volume.c \
 *       -o /tmp/test_uac_volume && /tmp/test_uac_volume
 *
 * 全部用例通过时打印 "OK (N cases)" 并以 0 退出。
 */
#include "uac_volume.h"

#include <assert.h>
#include <stdio.h>

static int cases;

static void expect_percent(const char *name, int db_q8, int want)
{
    const int got = uac_volume_q8_to_percent((int16_t)db_q8);

    if (got != want) {
        fprintf(stderr, "FAIL [%s]: q8=%d(%.4f dB) -> %d%%, want %d%%\n",
                name, db_q8, db_q8 / 256.0, got, want);
        assert(0 && "q8_to_percent 用例失败");
    }
    cases++;
}

static void expect_q8(const char *name, int percent, int want)
{
    const int got = uac_volume_percent_to_q8(percent);

    if (got != want) {
        fprintf(stderr, "FAIL [%s]: %d%% -> q8=%d(%.4f dB), want %d(%.4f dB)\n",
                name, percent, got, got / 256.0, want, want / 256.0);
        assert(0 && "percent_to_q8 用例失败");
    }
    cases++;
}

static void expect_bytes(const char *name, int db_q8, uint8_t lo, uint8_t hi)
{
    uint8_t le[3] = {0x5A, 0x5A, 0x5A};   /* 第三个是越界哨兵 */
    const uint8_t src[2] = {lo, hi};

    uac_volume_encode((int16_t)db_q8, le);
    if (le[0] != lo || le[1] != hi || le[2] != 0x5A) {
        fprintf(stderr, "FAIL [%s]: encode(%d) -> %02x %02x (哨兵 %02x), want %02x %02x\n",
                name, db_q8, le[0], le[1], le[2], lo, hi);
        assert(0 && "encode 用例失败");
    }
    if (uac_volume_decode(src) != (int16_t)db_q8) {
        fprintf(stderr, "FAIL [%s]: decode(%02x %02x) -> %d, want %d\n",
                name, lo, hi, uac_volume_decode(src), db_q8);
        assert(0 && "decode 用例失败");
    }
    cases++;
}

int main(void)
{
    /* ── 常量本身：dB 与 q8 的换算关系不能漂 ── */
    assert(UAC_VOL_MIN_Q8 == -50 * 256);   /* −50 dB */
    assert(UAC_VOL_MAX_Q8 == 0);           /*   0 dB */
    assert(UAC_VOL_RES_Q8 == 128);         /*  0.5 dB */
    /* 步进正好把 [MIN, MAX] 切成 100 段 = 101 档 = 百分比的档数。
     * 对不上就说明三个常量里有一个动过而另两个没跟上。 */
    assert((UAC_VOL_MAX_Q8 - UAC_VOL_MIN_Q8) / UAC_VOL_RES_Q8 == 100);
    cases++;

    /* ── 端点值双向往返 ── */
    expect_percent("MIN → 0%", UAC_VOL_MIN_Q8, 0);
    expect_q8("0% → MIN", 0, UAC_VOL_MIN_Q8);
    expect_percent("MAX → 100%", UAC_VOL_MAX_Q8, 100);
    expect_q8("100% → MAX", 100, UAC_VOL_MAX_Q8);

    /* ── 开机音量：−15 dB 必须正好是 70%，两个方向都要对 ──
     * codec_audio.c 用 UAC_VOL_DEFAULT_Q8 同时设硬件音量与 GET_CUR 的初值，
     * 这两条断言是「host 读到的开机音量 == 硬件实际音量」的唯一保证。 */
    assert(UAC_VOL_DEFAULT_Q8 == -15 * 256);
    cases++;
    expect_percent("开机值 → 70%", UAC_VOL_DEFAULT_Q8, 70);
    expect_q8("70% → 开机值", 70, UAC_VOL_DEFAULT_Q8);

    /* ── 与 esp_codec_dev 默认曲线逐点重合：q8 == −12800 + 128 × percent ──
     * 曲线是 vol 0..100 线性插值到 −50..0 dB，即 dB = −50 + 0.5×vol。
     * 这条如果破了，host 显示的 dB 就不是 codec 真正被设成的 dB。 */
    for (int p = 0; p <= 100; p++) {
        const int want = -12800 + 128 * p;

        if (uac_volume_percent_to_q8(p) != (int16_t)want) {
            fprintf(stderr, "FAIL [曲线]: %d%% -> %d, want %d\n",
                    p, uac_volume_percent_to_q8(p), want);
            assert(0 && "与 esp_codec_dev 默认曲线不重合");
        }
    }
    cases++;

    /* ── 全量往返：每一个合法百分比都能原样绕回来 ── */
    for (int p = 0; p <= 100; p++) {
        const int back = uac_volume_q8_to_percent(uac_volume_percent_to_q8(p));

        if (back != p) {
            fprintf(stderr, "FAIL [往返]: %d%% -> q8=%d -> %d%%\n",
                    p, uac_volume_percent_to_q8(p), back);
            assert(0 && "percent → q8 → percent 不是恒等");
        }
    }
    cases++;

    /* ── 单调性：音量条往上拖，百分比只增不减；且全程落在 0..100 内 ──
     * 「方向反了」与「中段塌陷」是这类换算最典型的两种错，逐个 q8 值扫一遍最直接。 */
    {
        int prev = -1;

        for (int q = UAC_VOL_MIN_Q8 - 2000; q <= UAC_VOL_MAX_Q8 + 2000; q++) {
            const int p = uac_volume_q8_to_percent((int16_t)q);

            if (p < 0 || p > 100) {
                fprintf(stderr, "FAIL [越界]: q8=%d -> %d%%\n", q, p);
                assert(0 && "百分比跑出 0..100");
            }
            if (p < prev) {
                fprintf(stderr, "FAIL [单调]: q8=%d -> %d%%，上一个是 %d%%\n", q, p, prev);
                assert(0 && "q8 上升时百分比却下降了");
            }
            prev = p;
        }
        assert(prev == 100);   /* 扫到顶必须是满音量，不能是 0（方向反了的典型症状） */
        cases++;
    }
    /* 单调**且真的在动**：中段每升 0.5 dB 就该多 1 个百分点。 */
    expect_percent("中点 −25 dB → 50%", -25 * 256, 50);
    expect_percent("中点上一档 −25.5 dB → 49%", -25 * 256 - 128, 49);
    expect_percent("中点下一档 −24.5 dB → 51%", -25 * 256 + 128, 51);

    /* ── 0x8000：UAC1 的「−∞ dB」特殊值，不是最小音量 ── */
    expect_percent("静音特殊值 → 0%", UAC_VOL_SILENCE_Q8, 0);
    expect_bytes("静音特殊值的线上编码", UAC_VOL_SILENCE_Q8, 0x00, 0x80);

    /* ── 越界钳位 ── */
    expect_percent("比 MIN 还低 1 档", UAC_VOL_MIN_Q8 - 128, 0);
    expect_percent("远低于 MIN(−80 dB)", -80 * 256, 0);
    expect_percent("比 MAX 高 1 档(+0.5 dB)", 128, 100);
    expect_percent("远高于 MAX(+120 dB)", 120 * 256, 100);
    expect_percent("int16 上界", 32767, 100);
    expect_q8("负百分比钳到 MIN", -1, UAC_VOL_MIN_Q8);
    expect_q8("超 100 钳到 MAX", 250, UAC_VOL_MAX_Q8);

    /* ── 有符号数：dB 是负的，这是本模块最容易错的一处 ──
     * −50 dB = −12800，在 16 位补码上就是 0xCE00。把它当无符号读会得到 52736，
     * 于是「最小音量」比「最大音量」还大，所有钳位判断集体反向。 */
    assert(UAC_VOL_MIN_Q8 == (int16_t)0xCE00);
    cases++;
    expect_bytes("−50 dB = 0xCE00", UAC_VOL_MIN_Q8, 0x00, 0xCE);
    expect_bytes("−15 dB = 0xF100", UAC_VOL_DEFAULT_Q8, 0x00, 0xF1);
    expect_bytes("0 dB = 0x0000", 0, 0x00, 0x00);
    expect_bytes("−0.5 dB = 0xFF80", -128, 0x80, 0xFF);
    expect_bytes("RES(+0.5 dB) = 0x0080", UAC_VOL_RES_Q8, 0x80, 0x00);
    /* 非整字节边界的负值：低字节非 0，最容易在移位/截断里翻车 */
    expect_bytes("−1/256 dB = 0xFFFF", -1, 0xFF, 0xFF);
    expect_percent("−1/256 dB 仍算满音量", -1, 100);

    /* decode 是 encode 的逆，且对整个 int16 值域成立 —— 包含全部负值。 */
    for (int q = -32768; q <= 32767; q++) {
        uint8_t le[2];

        uac_volume_encode((int16_t)q, le);
        if (uac_volume_decode(le) != (int16_t)q) {
            fprintf(stderr, "FAIL [编解码往返]: %d -> %02x %02x -> %d\n",
                    q, le[0], le[1], uac_volume_decode(le));
            assert(0 && "encode → decode 不是恒等");
        }
    }
    cases++;

    printf("OK (%d cases)\n", cases);
    return 0;
}
