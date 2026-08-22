/*
 * cam_tune.c 的宿主机回归测试：AE 控制律 + 曝光/增益分配 + CCM 系数反推。
 *
 * 为什么这几个函数**必须**在宿主机上测：它们的失败模式全是「上板才看得见、
 * 看见了也说不清」的那一类 ——
 *   振荡   画面一亮一暗地喘，肉眼只能说「不稳」，说不出是增益大了还是滞后长了；
 *   过冲   骤变光照下先白一片再黑一片，实机复现要靠手忙脚乱地盖镜头；
 *   除零   全黑画面（盖住镜头）时崩机，而那正是用户最容易做的动作；
 *   饱和   顶到上下限之后每拍都下发一次 I2C，白白占着挂了触摸的那条总线。
 * 这四件事在宿主机上都能**确定性地**构造出来，而且能跑几百拍看有没有极限环。
 *
 * 照 test_cam_frame_stats.c 的做法：无框架，main() + assert()，直接编译被测的
 * 真实源码（main/cam_tune.c），不是复制粘贴的另一份实现。
 *
 * 编译运行：
 *   cd firmware/test
 *   cc -std=c11 -Wall -Wextra -Werror -I../main test_cam_tune.c \
 *       ../main/cam_tune.c -o /tmp/test_cam_tune && /tmp/test_cam_tune
 *
 * 全部用例通过时打印 "OK (N cases)" 并以 0 退出。
 */
#include "cam_tune.h"

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int cases;

#define CHECK(cond, ...)                                    \
    do {                                                    \
        if (!(cond)) {                                      \
            fprintf(stderr, "FAIL: " __VA_ARGS__);          \
            fprintf(stderr, "\n");                          \
            assert(0 && #cond);                             \
        }                                                   \
        cases++;                                            \
    } while (0)

/*
 * 两张增益表，用途不同，**别合并**：
 *
 * gmap_coarse  8 档、间距极大（1.5×、2×…）。给 cam_ae_split() 的分档用例用：
 *              档位稀疏，「取不超过所需的最大一档」这条规则才看得出来。
 * gmap_fine    照 SC202CS 真表的形状造：从 1.000× 起按约 3% 一档一直排到 63×
 *              （真表 192 档、相邻约 3%，见 sensors/sc202cs/sc202cs.c 的
 *               sc202cs_abs_gain_val_map）。控制律的收敛用例必须用它 ——
 *              档位间距直接决定 AE 能停在离目标多近的地方，拿稀疏表测收敛
 *              等于在测一个真机上不存在的量化误差。
 */
static const uint32_t gmap_coarse[] = {1000, 1500, 2000, 4000, 8000, 16000, 32000, 63008};
#define GCOUNT_COARSE ((uint32_t)(sizeof(gmap_coarse) / sizeof(gmap_coarse[0])))

#define GCOUNT_FINE 145
static uint32_t gmap_fine[GCOUNT_FINE];

static void build_fine_gain_map(void)
{
    uint32_t v = 1000;
    for (uint32_t i = 0; i < GCOUNT_FINE; i++) {
        gmap_fine[i] = v;
        v = v + v * 3 / 100;          /* 每档 +3%，与真表的疏密同量级 */
        if (v > 63008)
            v = 63008;
    }
    /* 单调升是 cam_ae_split() 的前提（它靠单调性提前 break），钉死它。 */
    for (uint32_t i = 1; i < GCOUNT_FINE; i++)
        assert(gmap_fine[i] >= gmap_fine[i - 1]);
}

/* 曝光范围照 SC202CS 1280×720 模式：下限 0x08，上限 VTS(1250) − 6。 */
static cam_ae_limits_t lim = {
    .exp_min = 8,
    .exp_max = 1244,
    .gain_map = gmap_fine,
    .gain_count = GCOUNT_FINE,
};

static const cam_ae_limits_t lim_coarse = {
    .exp_min = 8,
    .exp_max = 1244,
    .gain_map = gmap_coarse,
    .gain_count = GCOUNT_COARSE,
};

/* ══ 曝光/增益分配 ═══════════════════════════════════════════════════ */

static void test_split(void)
{
    uint32_t e = 0, g = 0;

    /* 够用曝光解决的，一律不动增益 —— 增益是噪声来源，是垫底手段。 */
    cam_ae_split(500, &lim_coarse, &e, &g);
    CHECK(e == 500 && g == 0, "ev=500 应当全靠曝光：得到 exp=%u gain=%u", e, g);

    cam_ae_split(1244, &lim_coarse, &e, &g);
    CHECK(e == 1244 && g == 0, "ev 恰好等于曝光上限：得到 exp=%u gain=%u", e, g);

    /* 曝光顶到头之后才翻增益档。ev=2488 ⇒ 需要 2.0× ⇒ 第 2 档。 */
    cam_ae_split(2488, &lim_coarse, &e, &g);
    CHECK(e == 1244 && g == 2, "ev=2488 应当是 曝光上限 × 2.0×：得到 exp=%u gain=%u", e, g);

    /* 取「不超过所需」的最大一档，不能四舍五入到上面一档 ——
     * 宁可略暗一点，也不要让 AE 因为分配环节自己往上跳而在死区边缘打摆。 */
    cam_ae_split(2000, &lim_coarse, &e, &g);
    CHECK(e == 1244 && g == 1, "ev=2000 需要 1.607×，应落在 1.5× 那档：得到 gain=%u", g);

    /* 低于曝光下限：曝光钉在下限，增益回第 0 档。 */
    cam_ae_split(1, &lim_coarse, &e, &g);
    CHECK(e == lim_coarse.exp_min && g == 0, "ev=1 应当钉在下限：得到 exp=%u gain=%u", e, g);
    cam_ae_split(0, &lim_coarse, &e, &g);
    CHECK(e == lim_coarse.exp_min && g == 0, "ev=0 不许除零：得到 exp=%u gain=%u", e, g);

    /*
     * 增益上限必须生效，而且**永远不能给出 gain_count 这个下标** ——
     * 传感器驱动那侧的 MIN() 是 off-by-one 的，越界读只能靠这里挡住
     * （推导见 cam_tune.h 的 cam_ae_split ⚠️）。两张表都扫一遍。
     */
    for (uint32_t ev = 1; ev < 4000000u; ev = ev * 3 / 2 + 1) {
        cam_ae_split(ev, &lim_coarse, &e, &g);
        assert(g < GCOUNT_COARSE);
        assert(gmap_coarse[g] <= CAM_AE_GAIN_MAX_MILLI);
        assert(e >= lim_coarse.exp_min && e <= lim_coarse.exp_max);

        cam_ae_split(ev, &lim, &e, &g);
        assert(g < GCOUNT_FINE);
        assert(gmap_fine[g] <= CAM_AE_GAIN_MAX_MILLI);
        assert(e >= lim.exp_min && e <= lim.exp_max);
    }
    cases++;

    /* 非法参数不许崩、不许写脏内存。 */
    e = 1; g = 1;
    cam_ae_split(1000, NULL, &e, &g);
    CHECK(e == 0 && g == 0, "limits 为空时应给出 0/0");
    cam_ae_split(1000, &lim, NULL, NULL);        /* 不许崩 */
    const cam_ae_limits_t empty = {8, 1244, gmap_fine, 0};
    e = 1; g = 1;
    cam_ae_split(1000, &empty, &e, &g);
    CHECK(e == 0 && g == 0, "增益表为空时应给出 0/0");
    cases++;
}

/* ══ 控制律的单步行为 ═════════════════════════════════════════════════ */

/* 走满一个更新周期（前 CAM_AE_INTERVAL_TICKS−1 拍必然不动）。 */
static bool tick_period(cam_ae_state_t *st, uint8_t mean)
{
    bool changed = false;
    for (int i = 0; i < CAM_AE_INTERVAL_TICKS; i++)
        changed |= cam_ae_step(st, mean, &lim);
    return changed;
}

static void test_step_basics(void)
{
    cam_ae_state_t st;

    /* ── 更新频率限制：一个周期内只有一拍会动 ── */
    cam_ae_init(&st, &lim, 988, 0);
    CHECK(st.ev == 988 && st.exposure == 988 && st.gain_index == 0,
          "init 应当照抄传感器默认值：ev=%u exp=%u", st.ev, st.exposure);
    int changed_count = 0;
    for (int i = 0; i < CAM_AE_INTERVAL_TICKS * 4; i++)
        if (cam_ae_step(&st, 45, &lim))
            changed_count++;
    CHECK(changed_count == 4, "4 个周期应当只下发 4 次，实得 %d 次", changed_count);

    /* ── 死区：目标附近完全不动，并在若干拍后报收敛 ── */
    cam_ae_init(&st, &lim, 988, 0);
    for (int i = 0; i < CAM_AE_INTERVAL_TICKS * (CAM_AE_CONVERGE_TICKS + 2); i++)
        CHECK(!cam_ae_step(&st, CAM_AE_TARGET, &lim), "正中目标时不该动");
    CHECK(cam_ae_converged(&st), "连续落在死区内却没报收敛");
    CHECK(st.updates == 0, "死区内不该有任何下发，实得 %u 次", st.updates);

    /* 死区边界：[LOW, HIGH] 闭区间之内不动，之外要动。
     * ⚠️ 用 LOW/HIGH 而不是「目标 ± 死区」：官方死区是**非对称**的（−6/+2），
     *    写成对称式的话 CAM_AE_SOURCE = 1 下这四条会验一个不存在的边界。 */
    cam_ae_init(&st, &lim, 988, 0);
    CHECK(!tick_period(&st, CAM_AE_TARGET_HIGH), "死区上边界不该动");
    cam_ae_init(&st, &lim, 988, 0);
    CHECK(!tick_period(&st, CAM_AE_TARGET_LOW), "死区下边界不该动");
    cam_ae_init(&st, &lim, 988, 0);
    CHECK(tick_period(&st, CAM_AE_TARGET_HIGH + 1), "越过死区上边界应当动");
    cam_ae_init(&st, &lim, 988, 0);
    CHECK(tick_period(&st, CAM_AE_TARGET_LOW - 1), "越过死区下边界应当动");

    /* ── 方向：暗了加曝光，亮了减曝光 ── */
    cam_ae_init(&st, &lim, 988, 0);
    tick_period(&st, 45);                       /* 实机实测的那个欠曝值 */
    CHECK(st.ev > 988, "均值 45（欠曝）之后曝光量应当变大，实得 %u", st.ev);
    cam_ae_init(&st, &lim, 988, 0);
    tick_period(&st, 240);
    CHECK(st.ev < 988, "均值 240（过曝）之后曝光量应当变小，实得 %u", st.ev);

    /* ── 除零：全黑画面（盖住镜头）必须能处理，而且要往上调 ── */
    cam_ae_init(&st, &lim, 988, 0);
    tick_period(&st, 0);
    CHECK(st.ev > 988, "均值 0 时应当加曝光而不是崩溃/不动，实得 %u", st.ev);

    /* ── 单步限幅：再离谱的误差，一拍也不许超过 CAM_AE_STEP_MAX 倍 ── */
    cam_ae_init(&st, &lim, 988, 0);
    uint32_t prev = st.ev;
    for (int p = 0; p < 12; p++) {
        tick_period(&st, 0);                    /* 一直全黑 ⇒ 一直想往上冲 */
        CHECK(st.ev <= prev * CAM_AE_STEP_MAX,
              "第 %d 个周期一步涨了 %u → %u，超过 %d 倍限幅",
              p, prev, st.ev, CAM_AE_STEP_MAX);
        prev = st.ev;
    }

    /* ── 饱和：顶到上限之后不许再下发（否则每拍白发一串 I2C） ── */
    for (int p = 0; p < 10; p++)
        tick_period(&st, 0);
    const uint32_t at_top = st.updates;
    for (int p = 0; p < 10; p++)
        CHECK(!tick_period(&st, 0), "已经顶到曝光上限，不该再下发");
    CHECK(st.updates == at_top, "饱和之后下发次数不该再涨");
    CHECK(st.exposure == lim.exp_max, "饱和时曝光应当停在上限，实得 %u", st.exposure);
    CHECK(gmap_fine[st.gain_index] <= CAM_AE_GAIN_MAX_MILLI, "饱和时增益越过了上限");

    /* 反向饱和：一直过曝，最终停在最短曝光 + 最低增益，且同样不再下发。 */
    cam_ae_init(&st, &lim, 988, 0);
    for (int p = 0; p < 30; p++)
        tick_period(&st, 255);
    CHECK(st.exposure == lim.exp_min && st.gain_index == 0,
          "一直过曝应当停在下限，实得 exp=%u gain=%u", st.exposure, st.gain_index);
    const uint32_t at_bottom = st.updates;
    for (int p = 0; p < 10; p++)
        CHECK(!tick_period(&st, 255), "已经顶到下限，不该再下发");
    CHECK(st.updates == at_bottom, "下限饱和之后下发次数不该再涨");

    /* 参数非法不许崩 */
    CHECK(!cam_ae_step(NULL, 100, &lim), "st 为空应当直接返回 false");
    CHECK(!cam_ae_step(&st, 100, NULL), "limits 为空应当直接返回 false");
    CHECK(!cam_ae_converged(NULL), "converged(NULL) 应当是 false");

    /*
     * ── 量化停滞是**刻意接受**的行为，钉住它 ──
     * 增益档之间跨度很大时（这里用稀疏表），阻尼后的请求可能落回同一档 ⇒
     * 这一拍不下发。结果是 AE 停在离目标略远的地方，但**稳**。
     * 反过来「非要动一档」才是错的：那会在两档之间来回跳，正是要防的那种喘。
     * 真表相邻档差约 3%，而死区是 ±10%，所以真机上总是先进死区、轮不到停滞。
     *
     * ⓘ 预热周期数从 20 提到 40：AE 目标由 120 改成 62（对齐官方标定）之后，
     *   同样喂 45 的误差比小了一半多（120/45 = 2.67 → 62/45 = 1.38），阻尼后
     *   每周期只涨 1.19× 而不是限幅的 2×，走到停滞点自然要更多周期。
     *   验的性质没变，只是这条爬升路径变长了。
     */
    cam_ae_init(&st, &lim_coarse, 988, 0);
    for (int p = 0; p < 40; p++)
        tick_period(&st, 45);
    const uint32_t stalled = st.updates;
    for (int p = 0; p < 10; p++)
        tick_period(&st, 45);
    CHECK(st.updates == stalled, "稀疏增益表下停滞后不该再反复下发（%u → %u）",
          stalled, st.updates);
}

/* ══ 闭环仿真：这才是「不振荡」的真正证据 ═══════════════════════════ */

/*
 * 一个假传感器：亮度与曝光量成正比，直到 255 削顶。
 * scene 是场景照度因子（越大越亮），mean = ev × scene / 1000。
 *
 * ⚠️ **带滞后**：返回的是 lag 拍之前那次曝光设置下的亮度。真机上从「下发曝光」
 *    到「测到反映它的那一帧」最坏约 230 ms ≈ 2 拍多（推导见 cam_tune.h 的
 *    CAM_AE_INTERVAL_TICKS）。控制律必须在**有滞后**的条件下稳定 ——
 *    不带滞后的仿真是自欺欺人，任何比例控制器在零滞后下都不会振荡。
 */
#define LAG 3
static uint8_t fake_sensor(uint32_t ev_history[], int idx, uint32_t scene)
{
    const uint32_t ev = ev_history[(idx - LAG + 64) % 64];
    uint64_t m = ((uint64_t)ev * scene) / 1000u;
    return (uint8_t)(m > 255 ? 255 : m);
}

/* 跑一轮闭环，返回最后 stable_ticks 拍里有没有发生过任何调整。 */
static void run_loop(uint32_t scene, int ticks, bool expect_in_band)
{
    cam_ae_state_t st;
    cam_ae_init(&st, &lim, 988, 0);

    uint32_t hist[64];
    for (int i = 0; i < 64; i++)
        hist[i] = st.ev;

    int last_change_tick = -1;
    uint8_t mean = 0;
    for (int t = 0; t < ticks; t++) {
        mean = fake_sensor(hist, t, scene);
        if (cam_ae_step(&st, mean, &lim))
            last_change_tick = t;
        hist[t % 64] = st.ev;
    }

    /* 稳态判据 1：**后 1/3 的时间里一次都没再动** —— 极限环（周期性来回调整）
     * 正是「画面一亮一暗地喘」的数学形态，这条能直接把它抓出来。 */
    CHECK(last_change_tick < ticks * 2 / 3,
          "scene=%u：直到第 %d 拍（共 %d 拍）还在调整，疑似极限环",
          scene, last_change_tick, ticks);

    /* 稳态判据 2：亮度真的落进了死区（能达到目标的场景才要求）。 */
    if (expect_in_band) {
        CHECK((int)mean >= CAM_AE_TARGET_LOW && (int)mean <= CAM_AE_TARGET_HIGH,
              "scene=%u：收敛后亮度 %u 没落进死区 [%d, %d]",
              scene, mean, CAM_AE_TARGET_LOW, CAM_AE_TARGET_HIGH);
        CHECK(cam_ae_converged(&st), "scene=%u：亮度在死区内却没报收敛", scene);
    }
}

static void test_closed_loop(void)
{
    /*
     * 覆盖四个数量级的照度。每个都要求 ①最终不再动 ②亮度落进死区。
     * 起始点固定是传感器默认的 ev=988，所以这几档分别对应「要往上调很多」
     * 「几乎不用调」「要往下调很多」三类。
     */
    run_loop(1000, 90, true);    /* 目标 ev=120，需要大幅调暗 */
    run_loop(120,  90, true);    /* 目标 ev=1000，基本不用动 */
    run_loop(30,   90, true);    /* 目标 ev=4000 ⇒ 曝光顶格 + 增益 3.2× */
    run_loop(6,    90, true);    /* 目标 ev=20000 ⇒ 曝光顶格 + 增益 16× */

    /*
     * 两个够不着的极端：AE 只能顶在限位上。要求仍然是**最终不再动** ——
     * 顶不到目标不是问题，顶着限位反复下发才是问题。
     */
    run_loop(100000, 90, false); /* 太亮：最短曝光 + 最低增益仍然削顶 */
    run_loop(1,      90, false); /* 太暗：曝光与增益都顶格仍然不够 */
}

/* ══ CCM 系数反推 ════════════════════════════════════════════════════ */

static void test_awb(void)
{
    uint32_t r = 0, b = 0;

    /* 典型的「未做白平衡」画面：绿远高于红蓝。当前系数还是 1.000。 */
    cam_awb_suggest(60, 120, 70, 1000, 1000, &r, &b);
    CHECK(r == 2000, "R60/G120 应当建议 2.000×，实得 %u", r);
    CHECK(b == 1714, "B70/G120 应当建议 1.714×，实得 %u", b);

    /*
     * **幂等性**：这是这个式子里最容易写错、也最致命的一条 ——
     * 均值是「施加当前 CCM 之后」测到的，忘了把当前系数乘进去就会越调越偏。
     * 系数已经正确（三个均值相等）时，建议值必须等于当前值。
     */
    cam_awb_suggest(120, 120, 120, 1700, 1550, &r, &b);
    CHECK(r == 1700 && b == 1550, "已经平衡时建议值应当等于当前值，实得 R%u B%u", r, b);

    /* 一次完整的「测量 → 采纳 → 复测」：采纳建议后画面应当真的平衡。
     * 设未做校正时三通道的原始比例是 R:G:B = 60:120:70，当前系数 R×1.2 B×1.1
     * ⇒ 测得 R72 G120 B77 ⇒ 建议 R×2.0 B×1.714 ⇒ 再测正好三个都是 120。 */
    cam_awb_suggest(72, 120, 77, 1200, 1100, &r, &b);
    CHECK(r == 2000, "两步收敛：R 建议应当是 2.000×，实得 %u", r);
    CHECK(b >= 1700 && b <= 1730, "两步收敛：B 建议应当≈1.714×，实得 %u", b);

    /* 除零守卫：通道全黑时保持当前值，而不是给出荒唐建议或崩掉。 */
    cam_awb_suggest(0, 120, 0, 1700, 1550, &r, &b);
    CHECK(r == 1700 && b == 1550, "通道均值为 0 时应当保持当前值，实得 R%u B%u", r, b);

    /* 限幅：上限是硬件定点格式的 4.0，下限防一次误测把系数打到 0。 */
    cam_awb_suggest(1, 255, 1, 2000, 2000, &r, &b);
    CHECK(r == 4000 && b == 4000, "建议值应当限幅到 4.000×，实得 R%u B%u", r, b);
    cam_awb_suggest(255, 1, 255, 1000, 1000, &r, &b);
    CHECK(r == 250 && b == 250, "建议值应当限幅到 0.250×，实得 R%u B%u", r, b);

    /* 空指针不许崩 */
    cam_awb_suggest(60, 120, 70, 1000, 1000, NULL, NULL);
    cases++;
}

/* ══ 闭环 AWB：防护判据 ══════════════════════════════════════════════
 *
 * 这一组是**整个改动里最要紧的测试**。闭环 AWB 的头号失效模式不是「调不准」，
 * 而是**被单色场景带偏**：镜头怼着一堵红墙，灰世界认定红通道太强、把红压下去，
 * 结果红墙变灰、画面其余部分泛青。这种病在实机上很难复现得干净（要真的找一面
 * 红墙、还要保证 AE 已经稳了），但在宿主机上是一组确定的数字。
 */

/* 走满一个更新周期，返回其中**唯一那次真正的评估结果**（其余各拍都是「未到周期」）。 */
static cam_awb_reason_t awb_period(cam_awb_state_t *st, uint8_t lum,
                                   uint8_t r, uint8_t g, uint8_t b, bool ae_conv)
{
    cam_awb_reason_t verdict = CAM_AWB_SKIP_PERIOD;
    for (int i = 0; i < CAM_AWB_INTERVAL_TICKS; i++) {
        const cam_awb_reason_t rc = cam_awb_step(st, lum, r, g, b, ae_conv);
        if (rc != CAM_AWB_SKIP_PERIOD)
            verdict = rc;
    }
    return verdict;
}

/* BT.601 亮度，与 cam_frame_stats.c 的权重逐字一致（77/150/29，和为 256）。 */
static uint8_t lum_of(uint32_t r, uint32_t g, uint32_t b)
{
    return (uint8_t)((77u * r + 150u * g + 29u * b) >> 8);
}

/*
 * 一个「单色场景」用例：喂 200 拍，要求**增益一动不动**，且理由恒为「色偏过大」。
 *
 * 三组数字都是「AWB 尚未动过（增益还是静态初值 1.700/1.550）时，镜头怼着该物体
 * 会测到的通道均值」—— 也就是防护最该起作用的那一刻。亮度都落在
 * [LUM_MIN, LUM_MAX] 内（故意的：**不能靠暗场/过亮那两道闸蒙混过关**，
 * 必须是色偏这一道真的挡住了），AE 也传「已收敛」（同理）。
 */
static void mono_scene(const char *what, uint8_t r, uint8_t g, uint8_t b)
{
    const uint8_t lum = lum_of(r, g, b);
    CHECK(lum >= CAM_AWB_LUM_MIN && lum <= CAM_AWB_LUM_MAX,
          "%s：亮度 %u 落在暗场/过亮闸里了，这个用例就测不到色偏闸", what, lum);

    cam_awb_state_t st;
    cam_awb_init(&st);

    /*
     * 先证明**这道闸是承重的**：把统计直接交给灰世界，它会给出一个荒唐的建议 ——
     * 那正是「红墙变灰、画面泛青」在数字上的样子。
     */
    uint32_t sug_r = 0, sug_b = 0;
    cam_awb_suggest(r, g, b, st.gain_r_milli, st.gain_b_milli, &sug_r, &sug_b);
    CHECK(sug_r < CAM_AWB_GAIN_MIN_MILLI || sug_r > CAM_AWB_GAIN_MAX_MILLI ||
          sug_b < CAM_AWB_GAIN_MIN_MILLI || sug_b > CAM_AWB_GAIN_MAX_MILLI,
          "%s：灰世界给出的建议 R×%u B×%u 居然是合理的，这个用例没有说服力",
          what, sug_r, sug_b);

    for (int p = 0; p < 20; p++) {
        const cam_awb_reason_t rc = awb_period(&st, lum, r, g, b, true);
        CHECK(rc == CAM_AWB_SKIP_CAST,
              "%s(R%u G%u B%u lum%u)：第 %d 个周期的结论是「%s」，应当是「色偏过大」",
              what, r, g, b, lum, p, cam_awb_reason_str(rc));
    }
    CHECK(st.gain_r_milli == CAM_CCM_GAIN_R_MILLI && st.gain_b_milli == CAM_CCM_GAIN_B_MILLI,
          "%s：增益被带偏了 R×%u B×%u（应当纹丝不动）", what, st.gain_r_milli, st.gain_b_milli);
    CHECK(st.updates == 0, "%s：单色场景下不该有任何一次下发，实得 %u 次", what, st.updates);
}

static void test_awb_guards(void)
{
    cam_awb_state_t st;

    /* ── 防护③：三种单色场景，一种都不许把白平衡带偏 ── */
    mono_scene("红墙", 200, 60, 55);    /* 暖色大面积：R/B = 3.6× */
    mono_scene("绿植", 55, 150, 50);    /* 满屏树叶：G/B = 3.0× */
    mono_scene("蓝天", 70, 110, 210);   /* 仰拍天空：B/R = 3.0× */

    /*
     * ── 正对照：**普通混杂场景必须真的调** ──
     * 没有这一条，上面三条用「永远不更新」也能全过 —— 那不是防护，是关掉了 AWB。
     * 数字取「略偏黄的白墙」（正是用户实测的现象：B 偏低）：
     * R100 G120 B90，色偏 1.33× 远在闸内，建议 R×2.040 B×2.066 也都在合理范围。
     */
    cam_awb_init(&st);
    const uint8_t wr = 100, wg = 120, wb = 90;
    const cam_awb_reason_t rc = awb_period(&st, lum_of(wr, wg, wb), wr, wg, wb, true);
    CHECK(rc == CAM_AWB_APPLIED, "偏黄的白墙应当触发一次更新，实得「%s」",
          cam_awb_reason_str(rc));
    CHECK(st.gain_r_milli > CAM_CCM_GAIN_R_MILLI && st.gain_b_milli > CAM_CCM_GAIN_B_MILLI,
          "偏黄 ⇒ R/B 都该往上抬，实得 R×%u B×%u", st.gain_r_milli, st.gain_b_milli);
    /* 单步限幅：一个周期最多动 CAM_AWB_STEP_MAX_PCT%。 */
    CHECK(st.gain_b_milli <= CAM_CCM_GAIN_B_MILLI +
                             CAM_CCM_GAIN_B_MILLI * CAM_AWB_STEP_MAX_PCT / 100,
          "一个周期涨了 %u → %u，超过 %d%% 限幅",
          (unsigned)CAM_CCM_GAIN_B_MILLI, st.gain_b_milli, CAM_AWB_STEP_MAX_PCT);

    /* ── 防护①：暗场不更新（噪声主导，颜色比值纯属随机） ── */
    cam_awb_init(&st);
    CHECK(awb_period(&st, CAM_AWB_LUM_MIN - 1, 20, 30, 15, true) == CAM_AWB_SKIP_DARK,
          "亮度低于下限时应当报「暗场」");
    CHECK(st.updates == 0, "暗场下不该有任何下发");
    /* 边界：恰好等于下限时**不算**暗场（判据是 <，不是 ≤）。 */
    cam_awb_init(&st);
    CHECK(awb_period(&st, CAM_AWB_LUM_MIN, wr, wg, wb, true) != CAM_AWB_SKIP_DARK,
          "亮度恰好等于下限时不该被当成暗场");

    /* ── 防护②：过亮不更新（通道被 255 截断，比值失真） ── */
    cam_awb_init(&st);
    CHECK(awb_period(&st, CAM_AWB_LUM_MAX + 1, 250, 252, 248, true) == CAM_AWB_SKIP_BRIGHT,
          "亮度高于上限时应当报「过亮」");
    CHECK(st.updates == 0, "过亮时不该有任何下发");

    /* ── 防护④：建议增益跑出合理范围 ⇒ 整拍不动（不是钳到边界上采纳） ── */
    cam_awb_init(&st);
    st.gain_r_milli = 2900;      /* 已经接近上限，再往上就越界 */
    st.gain_b_milli = 2900;
    CHECK(awb_period(&st, lum_of(100, 120, 110), 100, 120, 110, true) == CAM_AWB_SKIP_RANGE,
          "建议值越界时应当报「增益越界」");
    CHECK(st.gain_r_milli == 2900 && st.gain_b_milli == 2900,
          "越界那一拍不许动，实得 R×%u B×%u", st.gain_r_milli, st.gain_b_milli);

    /* ── 与 AE 的交互：AE 没收敛就一步不走 ── */
    cam_awb_init(&st);
    for (int i = 0; i < CAM_AWB_INTERVAL_TICKS * 5; i++)
        CHECK(cam_awb_step(&st, lum_of(wr, wg, wb), wr, wg, wb, false) == CAM_AWB_SKIP_AE,
              "AE 未收敛时应当恒报「AE未稳」");
    CHECK(st.updates == 0, "AE 未收敛时不该有任何下发");
    /* 而且**不消耗更新周期**：AE 一稳下来，第一拍就能动（不用再等满 10 拍）。
     * 这是刻意的 —— 场景不可信的那段时间不算进周期里。 */
    CHECK(cam_awb_step(&st, lum_of(wr, wg, wb), wr, wg, wb, true) == CAM_AWB_APPLIED,
          "AE 一收敛就该立刻评估一次");

    /* ── 通道均值为 0：既不许除零，也不许当成「平衡」 ── */
    cam_awb_init(&st);
    CHECK(awb_period(&st, 100, 0, 120, 100, true) == CAM_AWB_SKIP_CAST,
          "某个通道全黑时应当按无穷大色偏挡住");
    CHECK(st.gain_r_milli == CAM_CCM_GAIN_R_MILLI, "全黑通道不许把增益带偏");

    /* ── 空指针不许崩 ── */
    cam_awb_step(NULL, 100, 100, 120, 90, true);
    cam_awb_init(NULL);
    CHECK(!cam_awb_converged(NULL), "converged(NULL) 应当是 false");
    for (int i = 0; i <= CAM_AWB_REASON_COUNT; i++)
        CHECK(cam_awb_reason_str((cam_awb_reason_t)i) != NULL, "理由字符串不许为空");
}

/* ══ 闭环 AWB：AE 与 AWB 同时在跑的联合仿真 ═════════════════════════
 *
 * 这才是「两个环不会互相打架」的真正证据。单独测任一个环都看不到耦合：
 * AWB 把红蓝增益抬上去，画面整体**变亮**，AE 会把这份增益当成扰动压回来；
 * AE 改曝光，三个通道均值一起变，AWB 又会把这份变化看进自己的反馈量。
 */

/* 一个假场景：照度 + 传感器三个通道的**原始**响应比（1000 = 与绿等同）。 */
typedef struct {
    uint32_t illum;               /* 绿通道均值 = ev × illum / 1000（未削顶前） */
    uint32_t raw_r, raw_g, raw_b;
} fake_scene_t;

/* 拍一张：把 ev 与两个 CCM 增益变成三个通道均值（255 削顶）。 */
static void fake_frame(const fake_scene_t *sc, uint32_t ev, uint32_t gr, uint32_t gb,
                       uint8_t *r, uint8_t *g, uint8_t *b, uint8_t *lum)
{
    const uint64_t base = ((uint64_t)ev * sc->illum) / 1000u;
    uint64_t vr = base * sc->raw_r / 1000u * gr / 1000u;
    uint64_t vg = base * sc->raw_g / 1000u;              /* 绿增益恒为 1.000 */
    uint64_t vb = base * sc->raw_b / 1000u * gb / 1000u;
    if (vr > 255) vr = 255;
    if (vg > 255) vg = 255;
    if (vb > 255) vb = 255;
    *r = (uint8_t)vr;
    *g = (uint8_t)vg;
    *b = (uint8_t)vb;
    *lum = lum_of((uint32_t)vr, (uint32_t)vg, (uint32_t)vb);
}

static void run_joint_loop(const fake_scene_t *sc, int ticks)
{
    cam_ae_state_t ae;
    cam_awb_state_t awb;
    cam_ae_init(&ae, &lim, 988, 0);
    cam_awb_init(&awb);

    /* 三个执行量各留一份历史：**带滞后**，理由与 AE 单独仿真那处相同
     * （不带滞后的仿真是自欺欺人，任何比例控制器在零滞后下都不会振荡）。 */
    uint32_t h_ev[64], h_gr[64], h_gb[64];
    for (int i = 0; i < 64; i++) {
        h_ev[i] = ae.ev;
        h_gr[i] = awb.gain_r_milli;
        h_gb[i] = awb.gain_b_milli;
    }

    int last_change = -1;
    uint8_t r = 0, g = 0, b = 0, lum = 0;
    for (int t = 0; t < ticks; t++) {
        const int old = (t - LAG + 64) % 64;
        fake_frame(sc, h_ev[old], h_gr[old], h_gb[old], &r, &g, &b, &lum);

        /* 顺序与固件里的 camera_csi_tune_tick() 一致：先 AE 后 AWB。 */
        if (cam_ae_step(&ae, lum, &lim))
            last_change = t;
        if (cam_awb_step(&awb, lum, r, g, b, cam_ae_converged(&ae)) == CAM_AWB_APPLIED)
            last_change = t;

        h_ev[t % 64] = ae.ev;
        h_gr[t % 64] = awb.gain_r_milli;
        h_gb[t % 64] = awb.gain_b_milli;
    }

    /* 判据 1：后 1/3 的时间里**两个环都不再动**。两个环互相激励形成的交替调整
     * （AWB 动一下 → AE 追一下 → AWB 又动一下）正是耦合失控的数学形态。 */
    CHECK(last_change < ticks * 2 / 3,
          "illum=%u：直到第 %d 拍（共 %d 拍）还在调整，AE/AWB 疑似互相激励",
          sc->illum, last_change, ticks);

    /* 判据 2：亮度落进 AE 的死区。 */
    CHECK((int)lum >= CAM_AE_TARGET_LOW && (int)lum <= CAM_AE_TARGET_HIGH,
          "illum=%u：收敛后亮度 %u 没落进 AE 死区 [%d, %d]",
          sc->illum, lum, CAM_AE_TARGET_LOW, CAM_AE_TARGET_HIGH);

    /* 判据 3：三个通道均值真的拉平了 —— 容差 8%，由 AWB 死区(5%) 与
     * 通道均值本身的整数量化叠加而来。这一条才是「白平衡对了」。 */
    const int dr = (int)r - (int)g, db = (int)b - (int)g;
    CHECK(dr <= (int)g * 8 / 100 && -dr <= (int)g * 8 / 100,
          "illum=%u：收敛后 R%u 与 G%u 差得太多", sc->illum, r, g);
    CHECK(db <= (int)g * 8 / 100 && -db <= (int)g * 8 / 100,
          "illum=%u：收敛后 B%u 与 G%u 差得太多", sc->illum, b, g);

    CHECK(cam_awb_converged(&awb), "illum=%u：AWB 拉平了却没报收敛", sc->illum);
    CHECK(awb.gain_r_milli >= CAM_AWB_GAIN_MIN_MILLI &&
          awb.gain_r_milli <= CAM_AWB_GAIN_MAX_MILLI &&
          awb.gain_b_milli >= CAM_AWB_GAIN_MIN_MILLI &&
          awb.gain_b_milli <= CAM_AWB_GAIN_MAX_MILLI,
          "illum=%u：收敛后的增益 R×%u B×%u 跑出了合理范围",
          sc->illum, awb.gain_r_milli, awb.gain_b_milli);
}

static void test_awb_closed_loop(void)
{
    /*
     * 传感器原始响应取 R 0.500 / G 1.000 / B 0.455 ⇒ 正确的增益是 R×2.000、
     * B×2.198，而开机初值是 R×1.700 / B×1.550 —— **恰好是用户实测的方向**
     * （B 偏低 ⇒ 画面偏黄）。AWB 要把这 8%/42% 的缺口自己补上。
     */
    const uint32_t raw_r = 500, raw_g = 1000, raw_b = 455;

    /* 三档照度：分别对应 AE 要大幅提亮 / 基本不动 / 要大幅压暗。
     * 每一档都要求两个环各自收敛，且**通道均值拉平**。 */
    fake_scene_t dim   = {60,  raw_r, raw_g, raw_b};
    fake_scene_t mid   = {120, raw_r, raw_g, raw_b};
    fake_scene_t bright = {900, raw_r, raw_g, raw_b};
    run_joint_loop(&dim,    400);
    run_joint_loop(&mid,    400);
    run_joint_loop(&bright, 400);

    /*
     * 已经平衡的场景（原始响应恰好等于初值的倒数）：AWB 应当**一次都不动**，
     * 并很快报收敛。这一条挡的是「幂等性写错了」——那种错的表现是白平衡明明
     * 对了还在慢慢漂移，实机上要盯几分钟才看得出来。
     */
    fake_scene_t ok = {120, 1000000u / CAM_CCM_GAIN_R_MILLI, 1000,
                       1000000u / CAM_CCM_GAIN_B_MILLI};
    cam_ae_state_t ae;
    cam_awb_state_t awb;
    cam_ae_init(&ae, &lim, 988, 0);
    cam_awb_init(&awb);
    uint32_t h_ev[64];
    for (int i = 0; i < 64; i++)
        h_ev[i] = ae.ev;
    for (int t = 0; t < 300; t++) {
        uint8_t r, g, b, lum;
        fake_frame(&ok, h_ev[(t - LAG + 64) % 64], awb.gain_r_milli, awb.gain_b_milli,
                   &r, &g, &b, &lum);
        cam_ae_step(&ae, lum, &lim);
        cam_awb_step(&awb, lum, r, g, b, cam_ae_converged(&ae));
        h_ev[t % 64] = ae.ev;
    }
    CHECK(awb.updates == 0, "本来就平衡的场景不该有任何一次白平衡下发，实得 %u 次",
          awb.updates);
    CHECK(cam_awb_converged(&awb), "本来就平衡的场景应当报收敛");
}

/* ══ 硬件白点统计：Σ → rg/bg ═════════════════════════════════════════ */

static void test_awb_ratios(void)
{
    uint32_t rg = 0xdeadbeef, bg = 0xdeadbeef;

    /* 常规一份：Σr/Σg = 0.5、Σb/Σg = 0.6。 */
    cam_awb_hw_stat_t s = { .counted = 10000, .sum_r = 500000,
                            .sum_g = 1000000, .sum_b = 600000 };
    CHECK(cam_awb_ratios(&s, &rg, &bg), "常规采样应当算得出来");
    CHECK(rg == 5000, "rg 应为 5000（0.5000），实得 %u", rg);
    CHECK(bg == 6000, "bg 应为 6000（0.6000），实得 %u", bg);

    /* 不可用的三种：空指针、counted = 0、Σg = 0。全部返回 false 且**不写出参**。 */
    rg = bg = 0x5a5a;
    CHECK(!cam_awb_ratios(NULL, &rg, &bg), "空采样必须被挡住");
    CHECK(!cam_awb_ratios(&s, NULL, &bg), "空出参必须被挡住");
    CHECK(!cam_awb_ratios(&s, &rg, NULL), "空出参必须被挡住");
    const cam_awb_hw_stat_t zero_cnt = { .counted = 0, .sum_r = 1, .sum_g = 1, .sum_b = 1 };
    CHECK(!cam_awb_ratios(&zero_cnt, &rg, &bg), "counted = 0 的采样必须被挡住");
    const cam_awb_hw_stat_t zero_g = { .counted = 100, .sum_r = 100, .sum_g = 0, .sum_b = 100 };
    CHECK(!cam_awb_ratios(&zero_g, &rg, &bg), "Σg = 0 必须被挡住（这里正是除零点）");
    CHECK(rg == 0x5a5a && bg == 0x5a5a, "被挡住时不该写出参");

    /*
     * **满量程不溢出**。1280×720 全部入选、三个通道都顶到 255：
     * Σ = 235,008,000，乘 10000 = 2.35e12 —— 用 uint32 算这里必炸，
     * 炸出来的 rg 是个随机数，而现场只会看到「白平衡莫名其妙地跑」。
     */
    const uint32_t full = 1280u * 720u;
    const cam_awb_hw_stat_t sat = { .counted = full, .sum_r = full * 255u,
                                    .sum_g = full * 255u, .sum_b = full * 255u };
    CHECK(cam_awb_ratios(&sat, &rg, &bg), "满量程采样应当算得出来");
    CHECK(rg == 10000 && bg == 10000, "满量程三通道相等 ⇒ rg = bg = 10000，实得 %u/%u",
          rg, bg);

    /*
     * 官方白点框的下界（cam_isp_cal.h 的 CAM_CAL_RG_MIN = 3801、
     * CAM_CAL_BG_MIN = 2903）必须能被这套定点**精确**表达 —— 控制律的
     * SKIP_RANGE 判据是拿 rg_q4 与这两个数直接比大小的，差一个量化单位就会
     * 在边界上得出相反的结论。
     * ⓘ 这里写字面量而不是 include cam_isp_cal.h：cam_tune 一族是纯逻辑，
     *   不依赖标定表（那是 cam_isp_map 那一族的事）。
     */
    const cam_awb_hw_stat_t corner = { .counted = 1000, .sum_r = 380100,
                                       .sum_g = 1000000, .sum_b = 290300 };
    CHECK(cam_awb_ratios(&corner, &rg, &bg), "白点框左下角应当算得出来");
    CHECK(rg == 3801 && bg == 2903,
          "白点框左下角应当精确落回官方框的下界，实得 %u/%u", rg, bg);

    /*
     * 统计侧黑电平扣除。CAM_STAT_BLC_PEDESTAL 是编译期常量，所以这里只能测
     * 「当前构建下的那一档」——**两档都要有断言**，靠 #if 分开写：
     * 默认档（0）要求恒等；打开档（16）按手算的值核对。
     * 这条用例的价值在于把「扣除是精确的（Σ − p×counted）」钉住 ——
     * 它是唯一能把 counted 用错成「全画面像素数」的地方。
     */
    const cam_awb_hw_stat_t ped = { .counted = 1000, .sum_r = 100000,
                                    .sum_g = 200000, .sum_b = 150000 };
    CHECK(cam_awb_ratios(&ped, &rg, &bg), "扣基座用例应当算得出来");
#if CAM_STAT_BLC_PEDESTAL == 0
    CHECK(rg == 5000 && bg == 7500, "基座 0 时必须是恒等变换，实得 %u/%u", rg, bg);
#elif CAM_STAT_BLC_PEDESTAL == 16
    /* Σ' = (100000, 200000, 150000) − 16×1000 = (84000, 184000, 134000)
     * ⇒ rg = 84000×10000/184000 = 4565、bg = 134000×10000/184000 = 7282。
     * 注意两个比值都**更偏离 1**：扣掉加性基座之后色度对比被还原，这正是要的。 */
    CHECK(rg == 4565 && bg == 7282, "基座 16 的手算值对不上，实得 %u/%u", rg, bg);
#endif

    /* 基座把某个通道减到 0 以下时钳到 0（不是回绕成天文数字）。 */
    const cam_awb_hw_stat_t tiny = { .counted = 1000, .sum_r = 1,
                                     .sum_g = 200000, .sum_b = 150000 };
    CHECK(cam_awb_ratios(&tiny, &rg, &bg), "极暗红通道仍应算得出来");
    CHECK(rg <= 100, "红通道几乎为 0 时 rg 必须接近 0，实得 %u", rg);
}

/* ══ 可调参数自身的合法性 ════════════════════════════════════════════ */

static void test_tunables(void)
{
    /* 这几条是「有人调参数时替他挡一下」，不是形式主义：
     * 目标 ± 死区必须留在 8 位量程内，否则死区判据在端点上永远成立/永远不成立。 */
    CHECK(CAM_AE_TARGET_LOW > 0 && CAM_AE_TARGET_HIGH < 255,
          "死区边界超出了 0..255，端点上的死区判据会永远成立或永远不成立");
    /* 目标必须在死区之内 —— 官方的死区是非对称的（56/62/64），很容易在只改
     * 其中一个数时把目标挪到区间外，那时 AE 会「一收敛就立刻又想动」。 */
    CHECK(CAM_AE_TARGET_LOW <= CAM_AE_TARGET && CAM_AE_TARGET <= CAM_AE_TARGET_HIGH,
          "目标亮度落在死区 [%d, %d] 之外", CAM_AE_TARGET_LOW, CAM_AE_TARGET_HIGH);
    CHECK(CAM_AE_DAMP_NUM > 0 && CAM_AE_DAMP_NUM <= CAM_AE_DAMP_DEN,
          "阻尼系数必须落在 (0, 1]，大于 1 会放大误差");
    CHECK(CAM_AE_STEP_MAX >= 2, "单步限幅小于 2 会让 AE 几乎动不了");
    CHECK(CAM_AE_INTERVAL_TICKS >= 1, "更新周期至少 1 拍");
    /* CCM 系数不能超出 rev < 3.0 定点格式的 4.0 上限，否则 esp_isp_ccm_configure()
     * 直接返回 ESP_ERR_INVALID_ARG —— 那会在实机上表现为「白平衡整个没生效」。 */
    CHECK(CAM_CCM_GAIN_R_MILLI <= 4000 && CAM_CCM_GAIN_G_MILLI <= 4000 &&
          CAM_CCM_GAIN_B_MILLI <= 4000, "CCM 系数超过硬件上限 4.000");
    CHECK(CAM_CCM_GAIN_R_MILLI > 0 && CAM_CCM_GAIN_G_MILLI > 0 &&
          CAM_CCM_GAIN_B_MILLI > 0, "CCM 系数必须为正");

    /* ── AWB 的那一组 ── */
    CHECK(CAM_AWB_GAIN_MIN_MILLI > 0 && CAM_AWB_GAIN_MIN_MILLI < CAM_AWB_GAIN_MAX_MILLI,
          "AWB 增益范围必须是个非空区间");
    CHECK(CAM_AWB_GAIN_MAX_MILLI <= 4000,
          "AWB 增益上限超过硬件定点格式的 4.000，esp_isp_ccm_configure() 会直接失败");
    /*
     * **静态初值必须落在 AWB 的合理范围内**。否则开机第一拍就会撞上「增益越界」
     * 这道闸：AWB 一步都走不了，而现场只看到「颜色没在动」，极难反查到是两组
     * 参数没对上。这条断言就是替改参数的人挡这一下。
     */
    CHECK(CAM_CCM_GAIN_R_MILLI >= CAM_AWB_GAIN_MIN_MILLI &&
          CAM_CCM_GAIN_R_MILLI <= CAM_AWB_GAIN_MAX_MILLI &&
          CAM_CCM_GAIN_B_MILLI >= CAM_AWB_GAIN_MIN_MILLI &&
          CAM_CCM_GAIN_B_MILLI <= CAM_AWB_GAIN_MAX_MILLI,
          "静态标定初值落在 AWB 的合理范围之外，AWB 会开机就被自己的闸卡死");
    CHECK(CAM_AWB_DAMP_NUM > 0 && CAM_AWB_DAMP_NUM <= CAM_AWB_DAMP_DEN,
          "AWB 阻尼系数必须落在 (0, 1]");
    CHECK(CAM_AWB_STEP_MAX_PCT > CAM_AWB_DEADBAND_PCT,
          "单步限幅不能小于死区，否则一步永远跨不出死区，AWB 会卡在原地反复下发");
    CHECK(CAM_AWB_LUM_MIN < CAM_AE_TARGET && CAM_AE_TARGET < CAM_AWB_LUM_MAX,
          "AE 的目标亮度必须落在 AWB 的可信亮度区间内，否则 AE 一收敛 AWB 就被暗场/过亮挡住");
    CHECK(CAM_AWB_CAST_MAX_PCT > 100, "色偏上限小于 1.00× 的话任何场景都过不了");
    /*
     * **AWB 必须比 AE 慢**。这是两个环解耦的第二条措施（时间尺度分离），
     * 写成断言是因为它是个很容易在「让 AWB 快一点」的念头下被改坏的不变量。
     */
    CHECK(CAM_AWB_INTERVAL_TICKS >= CAM_AE_INTERVAL_TICKS * 2,
          "AWB 的更新周期至少要是 AE 的两倍，否则两个环会互相追着跑");
}

int main(void)
{
    build_fine_gain_map();

    test_split();
    test_step_basics();
    test_closed_loop();
    test_awb();
    test_awb_guards();
    test_awb_closed_loop();
    test_awb_ratios();
    test_tunables();

    printf("OK (%d cases)\n", cases);
    return 0;
}
