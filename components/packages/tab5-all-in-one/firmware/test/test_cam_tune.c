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

    /* 死区边界：±DEADBAND 之内不动，之外要动。 */
    cam_ae_init(&st, &lim, 988, 0);
    CHECK(!tick_period(&st, CAM_AE_TARGET + CAM_AE_DEADBAND), "死区上边界不该动");
    cam_ae_init(&st, &lim, 988, 0);
    CHECK(!tick_period(&st, CAM_AE_TARGET - CAM_AE_DEADBAND), "死区下边界不该动");
    cam_ae_init(&st, &lim, 988, 0);
    CHECK(tick_period(&st, CAM_AE_TARGET + CAM_AE_DEADBAND + 1), "越过死区上边界应当动");
    cam_ae_init(&st, &lim, 988, 0);
    CHECK(tick_period(&st, CAM_AE_TARGET - CAM_AE_DEADBAND - 1), "越过死区下边界应当动");

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
     */
    cam_ae_init(&st, &lim_coarse, 988, 0);
    for (int p = 0; p < 20; p++)
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
        const int diff = (int)mean - CAM_AE_TARGET;
        CHECK(diff >= -CAM_AE_DEADBAND && diff <= CAM_AE_DEADBAND,
              "scene=%u：收敛后亮度 %u 没落进死区 [%d, %d]",
              scene, mean, CAM_AE_TARGET - CAM_AE_DEADBAND,
              CAM_AE_TARGET + CAM_AE_DEADBAND);
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

/* ══ 可调参数自身的合法性 ════════════════════════════════════════════ */

static void test_tunables(void)
{
    /* 这几条是「有人调参数时替他挡一下」，不是形式主义：
     * 目标 ± 死区必须留在 8 位量程内，否则死区判据在端点上永远成立/永远不成立。 */
    CHECK(CAM_AE_TARGET > CAM_AE_DEADBAND && CAM_AE_TARGET + CAM_AE_DEADBAND < 255,
          "目标亮度 ± 死区超出了 0..255");
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
}

int main(void)
{
    build_fine_gain_map();

    test_split();
    test_step_basics();
    test_closed_loop();
    test_awb();
    test_tunables();

    printf("OK (%d cases)\n", cases);
    return 0;
}
