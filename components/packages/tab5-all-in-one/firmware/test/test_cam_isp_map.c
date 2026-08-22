/*
 * cam_isp_map.c 宿主机回归测试。
 *
 * 为什么这一层值得测到这个密度：它是「官方标定表 → ISP 寄存器」之间**唯一**的
 * 算术层，而算错的表现全是**画面上说不清的偏差**（色偏一点、暗角修反了、暖光下
 * 档位来回跳），现场没有任何一条日志能把它与「传感器就这样」区分开。
 * 上板之前把它在宿主机上钉死，上板任务里就只剩「把结果喂给 IDF API」的胶水。
 *
 * 照 test_cam_tune.c / test_cam_frame_stats.c 的做法：无框架，main() + assert()，
 * **直接编译被测的真实源码**（main/cam_isp_map.c），不是复制粘贴的另一份实现。
 *
 * 编译运行：
 *   cd firmware/test
 *   cc -std=c11 -Wall -Wextra -Werror -I../main test_cam_isp_map.c \
 *       ../main/cam_isp_map.c -o /tmp/test_cam_isp_map && /tmp/test_cam_isp_map
 *
 * 全部用例通过时打印 "OK (N cases)" 并以 0 退出。
 */
#include "cam_isp_map.h"

#include "cam_isp_cal.h"
/* 只为拿 CAM_ENV_EV_BREAKS 这一个宏 —— 降级路径的断点必须与 cam_tune.h 里
 * 实际生效的那一组是同一份，两处各写一份迟早会有一处忘了改。
 * cam_tune.h 是纯逻辑头（不依赖 ESP-IDF），这里只用宏、不调它的函数。 */
#include "cam_tune.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static int cases;

/* 三组白平衡增益，都落在由官方白点轨迹反推的物理自洽范围 [1000, 3445] 内：
 * 一组日光典型、一组暖光极端、一组把两个增益都顶到上限的最坏情况。 */
static const struct { uint32_t kr, kb; } k_gains[] = {
    { 1786, 1858 },   /* 5040 K 的自洽增益 */
    { 1138, 3441 },   /* 2292 K 的自洽增益（kb 接近上限） */
    { 3445, 3445 },   /* 两个都顶到 §E.4 推出的上限，最坏情况 */
};
#define N_GAINS ((int)(sizeof k_gains / sizeof k_gains[0]))

static int32_t imax_abs(const int32_t v[9])
{
    int32_t m = 0;
    for (int i = 0; i < 9; i++) {
        const int32_t a = v[i] < 0 ? -v[i] : v[i];
        if (a > m) m = a;
    }
    return m;
}

/* ══ A. 按增益选档 ══════════════════════════════════════════════════ */

static void test_gain_slot(void)
{
    const uint16_t *g = cam_cal_bf_gain;      /* {1000,4000,8000,16000,24000,32000,64000} */
    const uint32_t n = CAM_CAL_BF_N;

    assert(cam_map_gain_slot(g, n, 0) == 0);            cases++;
    assert(cam_map_gain_slot(g, n, 500) == 0);          cases++;   /* 低于首档 */
    assert(cam_map_gain_slot(g, n, 1000) == 0);         cases++;   /* 恰在首档断点 */
    assert(cam_map_gain_slot(g, n, 3999) == 0);         cases++;   /* 断点之间取低档 */
    assert(cam_map_gain_slot(g, n, 4000) == 1);         cases++;   /* 恰在断点取该档 */
    assert(cam_map_gain_slot(g, n, 12000) == 2);        cases++;
    assert(cam_map_gain_slot(g, n, 64000) == 6);        cases++;
    assert(cam_map_gain_slot(g, n, 999999) == 6);       cases++;   /* 高于末档 */

    const uint16_t one[1] = { 5000 };
    assert(cam_map_gain_slot(one, 1, 0) == 0);          cases++;
    assert(cam_map_gain_slot(one, 1, 99999) == 0);      cases++;   /* n == 1 恒 0 */
    assert(cam_map_gain_slot(g, 0, 12000) == 0);        cases++;   /* 空表 */
    assert(cam_map_gain_slot(NULL, n, 12000) == 0);     cases++;   /* NULL */

    /* 全扫描：下标恒在 [0,n-1] 且随增益单调非减。 */
    uint32_t prev = 0;
    for (uint32_t x = 0; x <= 70000; x += 7) {
        const uint32_t s = cam_map_gain_slot(g, n, x);
        assert(s < n);
        assert(s >= prev);
        prev = s;
    }
    cases++;

    /* 每一档的断点值本身必须落回该档（表是升序的前提）。 */
    for (uint32_t i = 0; i < n; i++) {
        assert(cam_map_gain_slot(g, n, g[i]) == i);
        cases++;
    }
}

/* ══ A2. ×1000 → 硬件定点（进位与溢出是重点）═══════════════════════ */

/* 硬件位宽（soc_caps.h:363-373），别在测试里再发明一套。 */
#define DM_INT 2
#define DM_DEC 4    /* demosaic grad_ratio：2.4，步长 1/16 */
#define SH_INT 3
#define SH_DEC 5    /* sharpen h/m_freq_coeff：3.5，步长 1/32 */

static void chk_fixed(uint32_t milli, uint32_t ib, uint32_t db,
                      bool ok_exp, uint32_t i_exp, uint32_t d_exp)
{
    uint32_t i = 0xdead, d = 0xbeef;
    assert(cam_map_to_fixed(milli, ib, db, &i, &d) == ok_exp);
    assert(i == i_exp);
    assert(d == d_exp);
    cases++;
}

static void test_to_fixed(void)
{
    /* 官方 demosaic 四档，逐个核对（1.05 只能量化到 1.0625，是已知且可接受的 6%）。 */
    chk_fixed(1500, DM_INT, DM_DEC, true, 1, 8);      /* 1.5     精确 */
    chk_fixed(1250, DM_INT, DM_DEC, true, 1, 4);      /* 1.25    精确 */
    chk_fixed(1050, DM_INT, DM_DEC, true, 1, 1);      /* 1.05  → 1.0625 */
    chk_fixed(1000, DM_INT, DM_DEC, true, 1, 0);      /* 1.0     精确 */
    for (int i = 0; i < CAM_CAL_DEMOSAIC_N; i++) {
        uint32_t ip, dp;
        assert(cam_map_to_fixed(cam_cal_demosaic[i].grad_ratio_milli, DM_INT, DM_DEC, &ip, &dp));
        /* 量化误差不超过半个栅格（1/32 = 31 milli）。 */
        const int32_t back = (int32_t)(ip * 1000u + dp * 1000u / (1u << DM_DEC));
        const int32_t err = back - (int32_t)cam_cal_demosaic[i].grad_ratio_milli;
        assert(err > -32 && err < 32);
        cases++;
    }

    /* 官方 sharpen 的两个系数。1.625 恰好是 52/32（精确），其余是最近栅格。 */
    chk_fixed(1625, SH_INT, SH_DEC, true, 1, 20);     /* 1.625   精确 */
    chk_fixed(1525, SH_INT, SH_DEC, true, 1, 17);     /* 1.525 → 1.53125 */
    chk_fixed(1425, SH_INT, SH_DEC, true, 1, 14);     /* 1.425 → 1.4375  */
    chk_fixed(1325, SH_INT, SH_DEC, true, 1, 10);     /* 1.325 → 1.3125  */
    chk_fixed(1225, SH_INT, SH_DEC, true, 1, 7);      /* 1.225 → 1.21875 */
    for (int i = 0; i < CAM_CAL_SHARPEN_N; i++) {
        uint32_t ip, dp;
        assert(cam_map_to_fixed(cam_cal_sharpen[i].h_coeff_milli, SH_INT, SH_DEC, &ip, &dp));
        assert(ip < (1u << SH_INT) && dp < (1u << SH_DEC));
        assert(cam_map_to_fixed(cam_cal_sharpen[i].m_coeff_milli, SH_INT, SH_DEC, &ip, &dp));
        assert(ip < (1u << SH_INT) && dp < (1u << SH_DEC));
        cases++;
    }

    /* 零与整数：不该凭空冒出小数位。 */
    chk_fixed(0,    SH_INT, SH_DEC, true, 0, 0);
    chk_fixed(2000, SH_INT, SH_DEC, true, 2, 0);

    /* **进位**：0.99 在 1/32 栅格上舍成 32/32 ⇒ 必须进到整数位，
     * 而不是被 5 位的位域静默截断成 0（那会把 3.99 变成 3.00）。 */
    chk_fixed(3990, SH_INT, SH_DEC, true, 4, 0);
    chk_fixed(1990, DM_INT, DM_DEC, true, 2, 0);      /* 1.99 在 1/16 上同理 */
    /* 刚好不进位的邻居，证明上一条不是把所有值都推上去了。 */
    chk_fixed(3960, SH_INT, SH_DEC, true, 3, 31);     /* 0.96×32 = 30.72 → 31 */

    /* **溢出**：3 整数位装不下 8.0；返回 false 且钳到 7 + 31/32。 */
    chk_fixed(8000, SH_INT, SH_DEC, false, 7, 31);
    chk_fixed(4000, DM_INT, DM_DEC, false, 3, 15);    /* 2 整数位装不下 4.0 */
    /* 进位导致的溢出也要被抓住：3.999 → 4.0，2 整数位装不下。 */
    chk_fixed(3999, DM_INT, DM_DEC, false, 3, 15);
}

/* ══ A3. 带迟滞的档位跟踪器 ════════════════════════════════════════ */

static void test_slot_track(void)
{
    cam_slot_track_t t = { 0 };
    const uint32_t H = 3;

    /* 开机第一拍无条件下发，且 cur 立刻等于 want。 */
    assert(cam_slot_changed(&t, 5, H));   assert(t.cur == 5);   cases++;
    /* 同一个档再来多少拍都不动。 */
    for (int i = 0; i < 10; i++) {
        assert(!cam_slot_changed(&t, 5, H));
        cases++;
    }
    /* 新档要连续 3 拍才认。 */
    assert(!cam_slot_changed(&t, 2, H));  assert(t.cur == 5);   cases++;
    assert(!cam_slot_changed(&t, 2, H));  assert(t.cur == 5);   cases++;
    assert(cam_slot_changed(&t, 2, H));   assert(t.cur == 2);   cases++;

    /* **抖动不该换档**：新档与旧档交替出现时计数要被打断。 */
    for (int i = 0; i < 20; i++) {
        assert(!cam_slot_changed(&t, 7, H));
        assert(!cam_slot_changed(&t, 2, H));
        assert(t.cur == 2);
        cases++;
    }
    /* **两个新档互相打断**也不该换：7,9,7,9… 谁都连不够 3 拍。 */
    for (int i = 0; i < 20; i++) {
        assert(!cam_slot_changed(&t, 7, H));
        assert(!cam_slot_changed(&t, 9, H));
        assert(t.cur == 2);
        cases++;
    }
    /* 打断之后重新连够 3 拍，仍然换得动（计数被清干净了，不是永久卡死）。 */
    assert(!cam_slot_changed(&t, 7, H));
    assert(!cam_slot_changed(&t, 7, H));
    assert(cam_slot_changed(&t, 7, H));   assert(t.cur == 7);   cases++;

    /* hyst = 1 ⇒ 立即换档；hyst = 0 按 1 处理（不允许把迟滞短路成 0 拍）。 */
    cam_slot_track_t a = { 0 }, b = { 0 };
    assert(cam_slot_changed(&a, 0, 1));                         cases++;
    assert(cam_slot_changed(&a, 3, 1));   assert(a.cur == 3);   cases++;
    assert(cam_slot_changed(&b, 0, 0));                         cases++;
    assert(cam_slot_changed(&b, 3, 0));   assert(b.cur == 3);   cases++;

    /* 迟滞只延后、不丢失：连续指向新档 hyst 拍之后必然换成功。 */
    for (uint32_t h = 1; h <= 8; h++) {
        cam_slot_track_t s = { 0 };
        assert(cam_slot_changed(&s, 0, h));
        for (uint32_t i = 1; i < h; i++)
            assert(!cam_slot_changed(&s, 1, h));
        assert(cam_slot_changed(&s, 1, h));
        assert(s.cur == 1);
        cases++;
    }
}

/* ══ B. 按色温选档 + 插值权重 ═══════════════════════════════════════ */

static void test_cct_slot(void)
{
    const uint16_t *t = cam_cal_ccm_cct;      /* 1200 … 12000，19 档 */
    const uint32_t n = CAM_CAL_CCM_N;
    uint32_t w = 999;

    assert(cam_map_cct_slot(t, n, 0, &w) == 0 && w == 0);            cases++;
    assert(cam_map_cct_slot(t, n, 1200, &w) == 0 && w == 0);         cases++;
    assert(cam_map_cct_slot(t, n, 12000, &w) == n - 1 && w == 0);    cases++;
    assert(cam_map_cct_slot(t, n, 99999, &w) == n - 1 && w == 0);    cases++;

    /* 5040 ↔ 5090 这对 50 K 间距：中点应给出接近 128 的权重。 */
    const uint32_t i5040 = 9;
    assert(t[i5040] == 5040 && t[i5040 + 1] == 5090);
    assert(cam_map_cct_slot(t, n, 5040, &w) == i5040 && w == 0);     cases++;
    assert(cam_map_cct_slot(t, n, 5065, &w) == i5040 && w == 128);   cases++;
    assert(cam_map_cct_slot(t, n, 5089, &w) == i5040 && w == 250);   cases++;   /* 49×256/50 */

    const uint16_t one[1] = { 5000 };
    assert(cam_map_cct_slot(one, 1, 9000, &w) == 0 && w == 0);       cases++;
    assert(cam_map_cct_slot(t, 0, 5000, &w) == 0 && w == 0);         cases++;
    assert(cam_map_cct_slot(NULL, n, 5000, &w) == 0 && w == 0);      cases++;
    (void)cam_map_cct_slot(t, n, 5000, NULL);                        cases++;  /* 不许崩 */

    /* 每一档的断点值落回该档且 w=0；全扫描 w <= 256、下标不越界。 */
    for (uint32_t i = 0; i < n; i++) {
        assert(cam_map_cct_slot(t, n, t[i], &w) == i && w == 0);
        cases++;
    }
    for (uint32_t c = 500; c <= 13000; c += 3) {
        const uint32_t i = cam_map_cct_slot(t, n, c, &w);
        assert(i < n && w <= 256);
        if (i + 1 < n && w > 0)
            assert(c >= t[i] && c < t[i + 1]);
    }
    cases++;
}

/* ══ B2. 按色温取最近邻档（T13 的 LSC 选档规则）═════════════════════ */

static void test_cct_nearest(void)
{
    /* 官方 LSC 三档：2410 / 5210 / 8200 K。中点分别是 3810 与 6705。 */
    assert(CAM_CAL_LSC_N == 3);
    assert(cam_cal_lsc_cct[0] == 2410 && cam_cal_lsc_cct[1] == 5210 &&
           cam_cal_lsc_cct[2] == 8200);

    /* 三个档位中心各自映到自己。 */
    for (uint32_t i = 0; i < CAM_CAL_LSC_N; i++) {
        assert(cam_map_cct_nearest(cam_cal_lsc_cct, CAM_CAL_LSC_N, cam_cal_lsc_cct[i]) == i);
        cases++;
    }
    /* 两端钳位。 */
    assert(cam_map_cct_nearest(cam_cal_lsc_cct, CAM_CAL_LSC_N, 1000) == 0);   cases++;
    assert(cam_map_cct_nearest(cam_cal_lsc_cct, CAM_CAL_LSC_N, 99999) == 2);  cases++;

    /*
     * **对 CCT 单调非减**，且恰好有两个切换点。这是本函数唯一要守的性质 ——
     * 切换点比真正的中点晚约 (hi−lo)/256（q8 权重截断），三档上约 11 K，
     * 所以这里不去钉「3810 处换档」，而是钉「切换点落在中点右侧 32 K 之内」。
     */
    {
        uint32_t prev = 0, edges = 0;
        for (uint32_t k = 1000; k <= 12000; k++) {
            const uint32_t v = cam_map_cct_nearest(cam_cal_lsc_cct, CAM_CAL_LSC_N, k);
            assert(v >= prev && v <= 2);
            if (v != prev) {
                const uint32_t mid = (uint32_t)(cam_cal_lsc_cct[v - 1] + cam_cal_lsc_cct[v]) / 2;
                assert(k >= mid && k <= mid + 32);
                edges++;
            }
            prev = v;
        }
        assert(edges == 2);
        cases++;
    }

    /* 退化输入不许崩、不许越界。 */
    assert(cam_map_cct_nearest(NULL, 3, 5000) == 0);                         cases++;
    assert(cam_map_cct_nearest(cam_cal_lsc_cct, 0, 5000) == 0);              cases++;
    assert(cam_map_cct_nearest(cam_cal_lsc_cct, 1, 99999) == 0);             cases++;

    /*
     * 饱和度那一侧（T13 的另一半）：官方 acc.saturation 只有两档
     * {0 → 128, 4500 → 130}。这里钉住表本身，运行期的迟滞在 camera_csi.c。
     */
    assert(CAM_CAL_SATURATION_N == 2);
    assert(cam_cal_saturation[0].cct_k == 0 && cam_cal_saturation[0].value == 128);
    assert(cam_cal_saturation[1].cct_k == 4500 && cam_cal_saturation[1].value == 130);
    /* 128 = 1.000×，是「不配 color 块」的等价值；130 = 1.0156×。 */
    assert(cam_cal_saturation[1].value * 1000u / 128u == 1015);
    cases++;
}

/* ══ C. rg → CCT ════════════════════════════════════════════════════ */

static void test_cct_from_rg(void)
{
    /* 16 个标定点逐点回代：必须精确落回提取脚本算出的那个 K。 */
    for (uint32_t i = 0; i < CAM_CAL_CCT_N; i++) {
        assert(cam_cct_from_rg(cam_cal_cct_rg[i]) == cam_cal_cct_k[i]);
        cases++;
    }

    /* 两端钳位。 */
    assert(cam_cct_from_rg(0) == cam_cal_cct_k[0]);                             cases++;
    assert(cam_cct_from_rg(1) == cam_cal_cct_k[0]);                             cases++;
    assert(cam_cct_from_rg(0xFFFFFFFFu) == cam_cal_cct_k[CAM_CAL_CCT_N - 1]);   cases++;

    /* 单调性 —— §E.4 的整个理由就在这条上：查表 + 强制单调之后，
     * CCT 对 rg 必须**全程单调非增**，否则暖光端会来回跳档。 */
    uint32_t prev = 0xFFFFFFFFu;
    for (uint32_t rg = 3000; rg <= 9500; rg++) {
        const uint32_t k = cam_cct_from_rg(rg);
        assert(k <= prev);
        assert(k >= cam_cal_cct_k[CAM_CAL_CCT_N - 1] && k <= cam_cal_cct_k[0]);
        prev = k;
    }
    cases++;

    /* 相邻两点的中点：必须落在两端点之间（线性插值的最基本性质）。 */
    for (uint32_t i = 0; i + 1 < CAM_CAL_CCT_N; i++) {
        const uint32_t mid = (uint32_t)(cam_cal_cct_rg[i] + cam_cal_cct_rg[i + 1]) / 2;
        const uint32_t k = cam_cct_from_rg(mid);
        assert(k <= cam_cal_cct_k[i] && k >= cam_cal_cct_k[i + 1]);
        cases++;
    }
}

/* ══ D. CCM 按色温插值 ══════════════════════════════════════════════ */

static void row_sums(const int32_t m[9], int32_t s[3])
{
    for (int r = 0; r < 3; r++)
        s[r] = m[r * 3] + m[r * 3 + 1] + m[r * 3 + 2];
}

static void test_ccm_interp(void)
{
    int32_t m[9], s[3];
    const int32_t eye[9] = { 1000, 0, 0, 0, 1000, 0, 0, 0, 1000 };

    /* 两端与越界都是官方给的单位阵（钳位守卫）。 */
    cam_ccm_at_cct(1200, m);  assert(memcmp(m, eye, sizeof eye) == 0);   cases++;
    cam_ccm_at_cct(12000, m); assert(memcmp(m, eye, sizeof eye) == 0);   cases++;
    cam_ccm_at_cct(0, m);     assert(memcmp(m, eye, sizeof eye) == 0);   cases++;
    cam_ccm_at_cct(99999, m); assert(memcmp(m, eye, sizeof eye) == 0);   cases++;

    /* 恰在档上 ⇒ 逐元素等于该档原值。 */
    for (uint32_t i = 0; i < CAM_CAL_CCM_N; i++) {
        cam_ccm_at_cct(cam_cal_ccm_cct[i], m);
        for (int e = 0; e < 9; e++)
            assert(m[e] == cam_cal_ccm[i][e]);
        cases++;
    }

    /* 5040 ↔ 5090 的中点：每个元素都夹在两端之间。 */
    cam_ccm_at_cct(5065, m);
    for (int e = 0; e < 9; e++) {
        const int32_t a = cam_cal_ccm[9][e], b = cam_cal_ccm[10][e];
        const int32_t lo = a < b ? a : b, hi = a < b ? b : a;
        assert(m[e] >= lo && m[e] <= hi);
    }
    cases++;

    /* 19 档逐档验行和 —— 这是「WB 右乘不破坏保白」整条推导的前提。 */
    for (uint32_t i = 0; i < CAM_CAL_CCM_N; i++) {
        int32_t raw[9];
        for (int e = 0; e < 9; e++) raw[e] = cam_cal_ccm[i][e];
        row_sums(raw, s);
        for (int r = 0; r < 3; r++)
            assert(s[r] >= 985 && s[r] <= 1015);
        cases++;
    }

    /* 插值出来的中间矩阵行和同样成立（线性组合保持行和）。 */
    for (uint32_t c = 1200; c <= 12000; c += 37) {
        cam_ccm_at_cct(c, m);
        row_sums(m, s);
        for (int r = 0; r < 3; r++)
            assert(s[r] >= 985 && s[r] <= 1015);
    }
    cases++;
}

/* ══ E. CCM 折叠 + 强度钳制（本组最重要）══════════════════════════ */

static void test_ccm_fold(void)
{
    int32_t m[9], out[9], s[3];

    /* ── E1 行和不变式：任意 t，M(t) 的行和恒为 1000（整数截断误差 <= 2）──
     * 直接验 M(t)（即 kr=kb=1000 时的 P），因为「行和为 1」是 M(t) 的性质，
     * 右乘 W 只改列的缩放、不改这条不变式的成立方式。 */
    static const uint32_t ts[] = { 0, 1, 64, 128, 192, 255, 256 };
    for (uint32_t i = 0; i < CAM_CAL_CCM_N; i++) {
        for (int e = 0; e < 9; e++) m[e] = cam_cal_ccm[i][e];
        for (size_t ti = 0; ti < sizeof ts / sizeof ts[0]; ti++) {
            cam_ccm_fold_at(m, 1000, 1000, ts[ti], out);
            row_sums(out, s);
            for (int r = 0; r < 3; r++)
                assert(s[r] >= 998 && s[r] <= 1002);
        }
        cases++;
    }

    /* ── E2 中性面不变式：P · (1/kr, 1, 1/kb)ᵀ 三个分量彼此相差 <= 1% ──
     * 即：传感器看到中性面时，出来仍然精确中性、整体增益仍然精确为 1
     * （这正是「朝单位阵混合」不损失亮度的那条性质）。 */
    for (uint32_t i = 0; i < CAM_CAL_CCM_N; i++) {
        for (int e = 0; e < 9; e++) m[e] = cam_cal_ccm[i][e];
        for (int g = 0; g < N_GAINS; g++) {
            const uint32_t kr = k_gains[g].kr, kb = k_gains[g].kb;
            (void)cam_ccm_fold_wb(m, kr, kb, out);
            const int64_t w[3] = { 1000000 / kr, 1000, 1000000 / kb };
            int64_t y[3];
            for (int r = 0; r < 3; r++)
                y[r] = (out[r * 3] * w[0] + out[r * 3 + 1] * w[1] + out[r * 3 + 2] * w[2]) / 1000;
            int64_t lo = y[0], hi = y[0];
            for (int r = 1; r < 3; r++) { if (y[r] < lo) lo = y[r]; if (y[r] > hi) hi = y[r]; }
            assert(lo > 0);
            assert((hi - lo) * 100 <= lo);      /* <= 1% */
        }
        cases++;
    }

    /* ── E3 范围不变式：任意输入下 max|out| <= CAM_CCM_ABS_MAX_MILLI ── */
    for (uint32_t i = 0; i < CAM_CAL_CCM_N; i++) {
        for (int e = 0; e < 9; e++) m[e] = cam_cal_ccm[i][e];
        for (int g = 0; g < N_GAINS; g++) {
            (void)cam_ccm_fold_wb(m, k_gains[g].kr, k_gains[g].kb, out);
            assert(imax_abs(out) <= CAM_CCM_ABS_MAX_MILLI);
        }
        cases++;
    }

    /* ── E4 t = 0 的退化路径 ──
     * ⚠️ 计划 §T1 Step4 的 E-4 写的是「2292 K 档 + kr=kb=3445 ⇒ 返回 t=0」，
     *    **与数据不符**：那一组实际返回 t=11（4545 那个元素在 t=1/256 上只到
     *    1013×3.445 = 3489，离 3990 还远）。真相是：只要 kr/kb 被钳在 [1000,3445]，
     *    官方那 19 个矩阵**都不会**把 t 逼到 0 —— t=0 是理论下界，不是可达值。
     *    所以这里分两条测：
     *      (a) 用一个人造的极端矩阵（行和仍为 1000）把 t 真的逼到 0，
     *          验证退化结果**逐元素**等于 diag(kr, 1000, kb)；
     *      (b) 对官方 19 档验证 t=0 恒可行（二分的前提）且实际取到的 t > 0。 */
    {
        /* 行和：1000 / 1000 / (−1000000 − 999000 + 2000000) = 1000。 */
        const int32_t syn[9] = { 1000, 0, 0, 0, 1000, 0, -1000000, -999000, 2000000 };
        for (int g = 0; g < N_GAINS; g++) {
            const uint32_t kr = k_gains[g].kr, kb = k_gains[g].kb;
            assert(cam_ccm_fold_wb(syn, kr, kb, out) == 0);
            const int32_t want[9] = { (int32_t)kr, 0, 0, 0, 1000, 0, 0, 0, (int32_t)kb };
            assert(memcmp(out, want, sizeof want) == 0);
            cases++;
        }
    }
    for (uint32_t i = 0; i < CAM_CAL_CCM_N; i++) {
        for (int e = 0; e < 9; e++) m[e] = cam_cal_ccm[i][e];
        for (int g = 0; g < N_GAINS; g++) {
            assert(cam_ccm_fold_at(m, k_gains[g].kr, k_gains[g].kb, 0, out));
            const int32_t want[9] = { (int32_t)k_gains[g].kr, 0, 0, 0, 1000, 0,
                                      0, 0, (int32_t)k_gains[g].kb };
            assert(memcmp(out, want, sizeof want) == 0);
            assert(cam_ccm_fold_wb(m, k_gains[g].kr, k_gains[g].kb, out) > 0);
        }
        cases++;
    }

    /* ── E5 §D.4 那张表的逐档回归 ──
     * 每一档配上由官方白点轨迹反推的、**物理自洽**的 kr/kb，二分给出的 t 必须与
     * 计划 §D.4 表里那一列一致（表是 0..1 的小数，这里换算成 0..256 并留 ±2 的
     * 量化余量）。这条把「提取出来的矩阵」与「折叠实现」一起钉住了。 */
    static const struct { uint16_t cct; uint16_t kr, kb; uint16_t t_q8; } d4[] = {
        {  1200, 1138, 3444, 256 }, {  2292, 1138, 3441,  11 }, {  2517, 1174, 3192,  26 },
        {  2780, 1219, 2944,  47 }, {  3055, 1392, 2389, 107 }, {  3473, 1483, 2229, 166 },
        {  3800, 1547, 2120, 212 }, {  4193, 1607, 2006, 256 }, {  4583, 1685, 1932, 256 },
        {  5040, 1786, 1858, 256 }, {  5090, 1798, 1851, 256 }, {  5210, 1826, 1830, 256 },
        {  5476, 1886, 1780, 256 }, {  5770, 1965, 1738, 256 }, {  6000, 2033, 1709, 240 },
        {  6554, 2224, 1648, 224 }, {  7020, 2403, 1572, 155 }, {  7265, 2522, 1546, 131 },
        { 12000, 2625, 1518, 256 },
    };
    assert(sizeof d4 / sizeof d4[0] == CAM_CAL_CCM_N);
    for (uint32_t i = 0; i < CAM_CAL_CCM_N; i++) {
        assert(d4[i].cct == cam_cal_ccm_cct[i]);
        cam_ccm_at_cct(d4[i].cct, m);
        const uint32_t t = cam_ccm_fold_wb(m, d4[i].kr, d4[i].kb, out);
        const int32_t d = (int32_t)t - (int32_t)d4[i].t_q8;
        assert(d >= -2 && d <= 2);
        assert(imax_abs(out) <= CAM_CCM_ABS_MAX_MILLI);
        cases++;
    }
    /* §D.4 的读法：4193 K ~ 5770 K 一整段原样装得下，一点不用钳。 */
    for (uint32_t i = 7; i <= 13; i++)
        assert(d4[i].t_q8 == 256);
    cases++;

    /* ── E6 可行域是以 0 为起点的区间，且二分给出的正是最大可行 t ──
     * 这条守着二分本身的正确性：若可行集出现「洞」，二分就不再等价于线性搜索。 */
    for (uint32_t i = 0; i < CAM_CAL_CCM_N; i++) {
        for (int e = 0; e < 9; e++) m[e] = cam_cal_ccm[i][e];
        for (int g = 0; g < N_GAINS; g++) {
            const uint32_t t = cam_ccm_fold_wb(m, k_gains[g].kr, k_gains[g].kb, out);
            for (uint32_t x = 0; x <= 256; x++) {
                const bool ok = cam_ccm_fold_at(m, k_gains[g].kr, k_gains[g].kb, x, NULL);
                assert(ok == (x <= t));
            }
        }
        cases++;
    }

    /* ── E7 max|P(t)| 随 t 单调非减（257 个 t 扫一遍）── */
    for (uint32_t i = 0; i < CAM_CAL_CCM_N; i++) {
        for (int e = 0; e < 9; e++) m[e] = cam_cal_ccm[i][e];
        for (int g = 0; g < N_GAINS; g++) {
            int32_t prev = -1;
            for (uint32_t x = 0; x <= 256; x++) {
                cam_ccm_fold_at(m, k_gains[g].kr, k_gains[g].kb, x, out);
                const int32_t mx = imax_abs(out);
                assert(mx >= prev);
                prev = mx;
            }
        }
        cases++;
    }

    /* ── E8 t=256 直通时，结果就是 M·diag(kr,1,kb) 本身（没有被动过）── */
    cam_ccm_at_cct(5040, m);
    assert(cam_ccm_fold_wb(m, 1786, 1858, out) == 256);
    for (int e = 0; e < 9; e++) {
        const int32_t k = (e % 3 == 0) ? 1786 : ((e % 3 == 2) ? 1858 : 1000);
        assert(out[e] == (int32_t)(((int64_t)m[e] * k) / 1000));
    }
    cases++;

    /* ── E10 T10 的实际策略：min(t*, CAM_CCM_STRENGTH_MAX) ──
     * cam_ccm_fold_wb_clamped() 把「定点二分」与「人为总闸」合成一步。三条性质：
     *   ① 返回值恒等于 min(t*, t_max)（t_max > 256 按 256 处理）；
     *   ② 结果矩阵恒可行（可行域是 [0, t*]，取更小的 t 只会更安全）——
     *      这正是「把强度当黑电平的总闸」这个做法成立的全部理由；
     *   ③ t_max = 0 ⇒ 逐元素退回 diag(kr, 1, kb)，即 CAM_CCM_MODE=0 那条
     *      已实机验证的路径。**「钳到底 = 回到已知可用状态」这条要能被测到。** */
    {
        static const uint32_t tmaxs[] = { 0, 1, 64, 128, 192, 255, 256, 1000 };
        for (uint32_t i = 0; i < CAM_CAL_CCM_N; i++) {
            for (int e = 0; e < 9; e++) m[e] = cam_cal_ccm[i][e];
            for (int g = 0; g < N_GAINS; g++) {
                const uint32_t kr = k_gains[g].kr, kb = k_gains[g].kb;
                const uint32_t tstar = cam_ccm_fold_wb(m, kr, kb, out);
                for (size_t x = 0; x < sizeof tmaxs / sizeof tmaxs[0]; x++) {
                    uint32_t cap = tmaxs[x] > 256u ? 256u : tmaxs[x];
                    uint32_t tf = 12345;
                    int32_t got[9];
                    const uint32_t t = cam_ccm_fold_wb_clamped(m, kr, kb, tmaxs[x], got, &tf);
                    assert(tf == tstar);
                    assert(t == (tstar < cap ? tstar : cap));
                    assert(imax_abs(got) <= CAM_CCM_ABS_MAX_MILLI);
                    /* 与「先二分再单独折一次」逐元素一致 —— 合成没有改变语义。 */
                    int32_t ref[9];
                    cam_ccm_fold_at(m, kr, kb, t, ref);
                    assert(memcmp(got, ref, sizeof ref) == 0);
                    if (t == 0) {
                        const int32_t want[9] = { (int32_t)kr, 0, 0, 0, 1000, 0,
                                                  0, 0, (int32_t)kb };
                        assert(memcmp(got, want, sizeof want) == 0);
                    }
                }
            }
            cases++;
        }
        /* t_feasible 可传 NULL（调用方只要结果时不该被迫准备一个变量）。 */
        cam_ccm_at_cct(5040, m);
        assert(cam_ccm_fold_wb_clamped(m, 1786, 1858, 192, out, NULL) == 192);
    }
    cases++;

    /* ── E9 退化输入：kr = kb = 0 不许崩、不许越界 ──
     * 这不是一个会真实出现的工作点（调用方把增益钳在 [1000,3445]），只是守着
     * 「输入再离谱也给得出一个合法矩阵」。第 0/2 列被增益清零，第 1 列不受影响
     * （它乘的是常数 1000），于是 t 直通到 256。 */
    cam_ccm_at_cct(5040, m);
    assert(cam_ccm_fold_wb(m, 0, 0, out) == 256);
    for (int e = 0; e < 9; e++)
        assert(out[e] == ((e % 3 == 1) ? m[e] : 0));
    assert(imax_abs(out) <= CAM_CCM_ABS_MAX_MILLI);
    cases++;
}

/* ══ F. AE 加权 + quorum 剔除 ═══════════════════════════════════════ */

/* 官方权重表的总和，手算：6 + 9 + 12 + 9 + 6 = 42。 */
#define AE_WSUM 42

static void test_ae(void)
{
    uint8_t lum[25], nd, nb;

    /* 权重表本身：总和必须是 42，中心块必须是最重的一块。 */
    {
        uint32_t sum = 0;
        for (int i = 0; i < 25; i++) sum += cam_cal_ae_weight[i];
        assert(sum == AE_WSUM);
        assert(cam_cal_ae_weight[12] == 4);
        cases++;
    }

    /* 全均匀 ⇒ 加权均值等于该值本身，两个计数都是 0。 */
    memset(lum, 100, sizeof lum);
    assert(cam_ae_weighted_mean(lum, &nd, &nb) == 100 && nd == 0 && nb == 0);   cases++;

    /* 单块极亮（中心，权重 4，但 200 < 239 不触发保护）：
     * (42×100 + 4×100) / 42 = 4600/42 = 109.5 ⇒ 110。 */
    memset(lum, 100, sizeof lum);
    lum[12] = 200;
    assert(cam_ae_weighted_mean(lum, &nd, &nb) == 110 && nd == 0 && nb == 0);   cases++;

    /* 4 块暗（权重 1+1+2+1 = 5）：**未达 quorum(5)，不剔除**。
     * (42−5)×100 / 42 = 3700/42 = 88.1 ⇒ 88。 */
    memset(lum, 100, sizeof lum);
    for (int i = 0; i < 4; i++) lum[i] = 0;
    assert(cam_ae_weighted_mean(lum, &nd, &nb) == 88 && nd == 4 && nb == 0);    cases++;

    /* 5 块暗（权重 1+1+2+1+1 = 6）：**达标，剔除** ⇒ 3600/36 = 100。 */
    memset(lum, 100, sizeof lum);
    for (int i = 0; i < 5; i++) lum[i] = 0;
    assert(cam_ae_weighted_mean(lum, &nd, &nb) == 100 && nd == 5 && nb == 0);   cases++;

    /* 2 块亮：未达 quorum(3)，不剔除 ⇒ (40×100 + 2×255)/42 = 4510/42 = 107.4 ⇒ 107。 */
    memset(lum, 100, sizeof lum);
    lum[0] = lum[1] = 255;
    assert(cam_ae_weighted_mean(lum, &nd, &nb) == 107 && nd == 0 && nb == 2);   cases++;

    /* 3 块亮（权重 1+1+2 = 4）：达标，剔除 ⇒ 3800/38 = 100。 */
    memset(lum, 100, sizeof lum);
    lum[0] = lum[1] = lum[2] = 255;
    assert(cam_ae_weighted_mean(lum, &nd, &nb) == 100 && nd == 0 && nb == 3);   cases++;

    /* 暗与亮的 quorum 各自独立生效：5 暗（前 5 块，w=6）+ 3 亮（末 3 块，w=1+1+... ）。 */
    memset(lum, 100, sizeof lum);
    for (int i = 0; i < 5; i++) lum[i] = 0;
    for (int i = 22; i < 25; i++) lum[i] = 255;
    {
        uint32_t ws = 0;
        for (int i = 5; i < 22; i++) ws += cam_cal_ae_weight[i];
        assert(cam_ae_weighted_mean(lum, &nd, &nb) == 100 && nd == 5 && nb == 3);
        assert(ws > 0);
        cases++;
    }

    /* 25 块全暗 ⇒ 全被剔除 ⇒ 退回无权算术平均（0）。 */
    memset(lum, 0, sizeof lum);
    assert(cam_ae_weighted_mean(lum, &nd, &nb) == 0 && nd == 25 && nb == 0);    cases++;

    /* 25 块全亮 ⇒ 全被剔除 ⇒ 退回无权算术平均（255）。 */
    memset(lum, 255, sizeof lum);
    assert(cam_ae_weighted_mean(lum, &nd, &nb) == 255 && nd == 0 && nb == 25);  cases++;

    /* 阈值是严格不等号：14 不算暗、239 不算亮；13 与 240 才算。 */
    memset(lum, CAM_CAL_AE_LOW_THRESH, sizeof lum);
    assert(cam_ae_weighted_mean(lum, &nd, &nb) == CAM_CAL_AE_LOW_THRESH && nd == 0);   cases++;
    memset(lum, CAM_CAL_AE_LOW_THRESH - 1, sizeof lum);
    assert(cam_ae_weighted_mean(lum, &nd, &nb) == CAM_CAL_AE_LOW_THRESH - 1 && nd == 25); cases++;
    memset(lum, CAM_CAL_AE_HIGH_THRESH, sizeof lum);
    assert(cam_ae_weighted_mean(lum, &nd, &nb) == CAM_CAL_AE_HIGH_THRESH && nb == 0);  cases++;
    memset(lum, CAM_CAL_AE_HIGH_THRESH + 1, sizeof lum);
    assert(cam_ae_weighted_mean(lum, &nd, &nb) == CAM_CAL_AE_HIGH_THRESH + 1 && nb == 25); cases++;

    /* 空指针：返回 0，两个计数清零；计数指针本身也允许为 NULL。 */
    nd = nb = 7;
    assert(cam_ae_weighted_mean(NULL, &nd, &nb) == 0 && nd == 0 && nb == 0);    cases++;
    memset(lum, 100, sizeof lum);
    assert(cam_ae_weighted_mean(lum, NULL, NULL) == 100);                       cases++;

    /* 结果恒落在输入的 [min, max] 内（加权平均的基本性质），扫一批随机形状。 */
    for (uint32_t seed = 1; seed < 400; seed++) {
        uint32_t x = seed * 2654435761u;
        uint8_t lo = 255, hi = 0;
        for (int i = 0; i < 25; i++) {
            x = x * 1664525u + 1013904223u;
            lum[i] = (uint8_t)(x >> 24);
            if (lum[i] < lo) lo = lum[i];
            if (lum[i] > hi) hi = lum[i];
        }
        const uint8_t r = cam_ae_weighted_mean(lum, &nd, &nb);
        assert(r >= lo && r <= hi);
        assert(nd <= 25 && nb <= 25);
    }
    cases++;
}

/* ══ G. 直方图归约 ══════════════════════════════════════════════════ */

static void test_hist(void)
{
    uint32_t bins[16];
    uint8_t mean, bp, dp;

    /* 全零 ⇒ 三个输出都是 0（与「统计到了但全黑」不共用哨兵：那种情况 bins[0] 非 0）。 */
    memset(bins, 0, sizeof bins);
    cam_hist_stats(bins, &mean, &bp, &dp);
    assert(mean == 0 && bp == 0 && dp == 0);                cases++;

    /* 单 bin 0 ⇒ 代表值 8，暗块 100%。 */
    memset(bins, 0, sizeof bins);
    bins[0] = 5;
    cam_hist_stats(bins, &mean, &bp, &dp);
    assert(mean == 8 && dp == 100 && bp == 0);              cases++;

    /* 单 bin 15 ⇒ 代表值 248，亮块 100%。 */
    memset(bins, 0, sizeof bins);
    bins[15] = 5;
    cam_hist_stats(bins, &mean, &bp, &dp);
    assert(mean == 248 && bp == 100 && dp == 0);            cases++;

    /* 均匀 ⇒ 均值 128（Σ(16i+8)/16 = 128），两端各占 1/16 = 6.25% ⇒ 6。 */
    for (int i = 0; i < 16; i++) bins[i] = 10;
    cam_hist_stats(bins, &mean, &bp, &dp);
    assert(mean == 128 && bp == 6 && dp == 6);              cases++;

    /* 单 bin i ⇒ 均值恰好是该 bin 的代表值 16i+8。 */
    for (int i = 0; i < 16; i++) {
        memset(bins, 0, sizeof bins);
        bins[i] = 1234;
        cam_hist_stats(bins, &mean, NULL, NULL);
        assert(mean == (uint8_t)(16 * i + 8));
        cases++;
    }

    /* 一批随机形状：mean ∈ [8,248]、bright+dark <= 100。 */
    for (uint32_t seed = 1; seed < 300; seed++) {
        uint32_t x = seed * 40503u + 7u;
        for (int i = 0; i < 16; i++) {
            x = x * 1664525u + 1013904223u;
            bins[i] = x >> 20;
        }
        cam_hist_stats(bins, &mean, &bp, &dp);
        assert(mean >= 8 && mean <= 248);
        assert((uint32_t)bp + (uint32_t)dp <= 100);
    }
    cases++;

    /* 极大计数不溢出：16 个 bin 各 2^32−1。 */
    for (int i = 0; i < 16; i++) bins[i] = 0xFFFFFFFFu;
    cam_hist_stats(bins, &mean, &bp, &dp);
    assert(mean == 128 && bp == 6 && dp == 6);              cases++;

    /* 空指针与输出指针可选。 */
    cam_hist_stats(NULL, &mean, &bp, &dp);
    assert(mean == 0 && bp == 0 && dp == 0);                cases++;
    for (int i = 0; i < 16; i++) bins[i] = 1;
    cam_hist_stats(bins, NULL, NULL, NULL);                 cases++;   /* 不许崩 */
}

/* ══ H. env.luma 与 gamma 选档 ══════════════════════════════════════ */

static void test_env_gamma(void)
{
    /* §E.5 的四个反推值：AE 收敛（scene_mean == target）时，
     * ev = 16556 / 8306 / 2775 / 833 必须**恰好**落在官方四个断点上。 */
    static const struct { uint32_t ev; uint16_t env_q1; } bp[] = {
        { 16556, 151 }, { 8306, 301 }, { 2775, 901 }, { 833, 3001 },
    };
    for (size_t i = 0; i < sizeof bp / sizeof bp[0]; i++) {
        assert(cam_env_luma_q1(bp[i].ev, CAM_CAL_AE_TARGET, CAM_CAL_AE_TARGET) == bp[i].env_q1);
        assert(cam_cal_gamma_luma_q1[i] == bp[i].env_q1);
        cases++;
    }

    /* 除零守卫。 */
    assert(cam_env_luma_q1(0, 62, 62) == 0);                cases++;
    assert(cam_env_luma_q1(1000, 62, 0) == 0);              cases++;

    /* env 对 scene_mean 单调非减、对 ev 单调非增（两条方向性）。 */
    {
        uint32_t prev = 0;
        for (uint32_t sm = 1; sm <= 255; sm++) {
            const uint32_t e = cam_env_luma_q1(1000, (uint8_t)sm, 62);
            assert(e >= prev);
            prev = e;
        }
        cases++;
        prev = 0xFFFFFFFFu;
        for (uint32_t ev = 8; ev <= 19904; ev += 8) {
            const uint32_t e = cam_env_luma_q1(ev, 62, 62);
            assert(e <= prev);
            prev = e;
        }
        cases++;
    }
    /* 我们的 ev 值域 [8, 19904] 必须把四个断点全部包住（§E.5 的证伪判据）。 */
    assert(cam_env_luma_q1(19904, 62, 62) < cam_cal_gamma_luma_q1[0]);          cases++;
    assert(cam_env_luma_q1(8, 62, 62) > cam_cal_gamma_luma_q1[CAM_CAL_GAMMA_N - 1]); cases++;

    /* ── H2 降级路径 cam_env_luma_from_ev() ──
     * 用官方 k 反推的那四个 ev 断点时，它与 cam_env_luma_q1(ev, target, target)
     * 必须给出**同一条曲线**（k/ev 在 1/ev 上是直线，四个锚点也在这条直线上）
     * ⇒ 翻 CAM_ENV_MODEL 这个开关本身不改变行为，改变只来自把断点换成实测值。 */
    {
        static const uint32_t brk[CAM_CAL_GAMMA_N] = CAM_ENV_EV_BREAKS;

        /* 四个锚点逐点命中官方断点。 */
        for (uint32_t i = 0; i < CAM_CAL_GAMMA_N; i++) {
            assert(cam_env_luma_from_ev(brk[i], brk) == cam_cal_gamma_luma_q1[i]);
            cases++;
        }
        /* 两端钳位：ev 更大 ⇒ 仍是第 0 档的断点值；ev 更小 ⇒ 末档。 */
        assert(cam_env_luma_from_ev(19904, brk) == cam_cal_gamma_luma_q1[0]);   cases++;
        assert(cam_env_luma_from_ev(8, brk) ==
               cam_cal_gamma_luma_q1[CAM_CAL_GAMMA_N - 1]);                     cases++;
        /* 与 k/ev 模型在整个值域上一致（钳位区之外，允许 1 个量化单位的差）。 */
        for (uint32_t ev = brk[CAM_CAL_GAMMA_N - 1]; ev <= brk[0]; ev += 7) {
            const int64_t a = cam_env_luma_from_ev(ev, brk);
            const int64_t b = cam_env_luma_q1(ev, CAM_CAL_AE_TARGET, CAM_CAL_AE_TARGET);
            assert(a - b <= 1 && b - a <= 1);
        }
        cases++;
        /* 对 ev 单调非增（选档标量必须单调，否则会在光照渐变时来回跳档）。 */
        {
            uint32_t prev = 0xFFFFFFFFu;
            for (uint32_t ev = 1; ev <= 24000; ev++) {
                const uint32_t e = cam_env_luma_from_ev(ev, brk);
                assert(e <= prev);
                prev = e;
            }
            cases++;
        }
        /* 断点换成实测值时，四个官方 luma 断点仍然是锚点（曲线形状不变、位置变）。 */
        {
            static const uint32_t mine[CAM_CAL_GAMMA_N] = { 9000, 4000, 1500, 400 };
            for (uint32_t i = 0; i < CAM_CAL_GAMMA_N; i++)
                assert(cam_env_luma_from_ev(mine[i], mine) == cam_cal_gamma_luma_q1[i]);
            uint32_t prev = 0xFFFFFFFFu;
            for (uint32_t ev = 1; ev <= 24000; ev++) {
                const uint32_t e = cam_env_luma_from_ev(ev, mine);
                assert(e <= prev);
                prev = e;
            }
            cases++;
        }
        /* 守门：ev = 0 / 空指针 / 断点非降序都不许崩、不许除零。 */
        assert(cam_env_luma_from_ev(0, brk) == 0);                              cases++;
        assert(cam_env_luma_from_ev(1000, NULL) == 0);                          cases++;
        {
            static const uint32_t bad[CAM_CAL_GAMMA_N] = { 5000, 5000, 5000, 5000 };
            (void)cam_env_luma_from_ev(4000, bad);   /* 不许崩 */
            cases++;
        }
    }

    /* 无迟滞时（cur 越界 ⇒ 开机第一拍）的选档：断点处取该档。 */
    assert(cam_gamma_slot(0, 99) == 0);                     cases++;
    assert(cam_gamma_slot(151, 99) == 0);                   cases++;
    assert(cam_gamma_slot(152, 99) == 1);                   cases++;
    assert(cam_gamma_slot(301, 99) == 1);                   cases++;
    assert(cam_gamma_slot(302, 99) == 2);                   cases++;
    assert(cam_gamma_slot(901, 99) == 2);                   cases++;
    assert(cam_gamma_slot(902, 99) == 3);                   cases++;
    assert(cam_gamma_slot(3001, 99) == 3);                  cases++;
    assert(cam_gamma_slot(999999, 99) == 3);                cases++;

    /* 迟滞（luma_min_step = 3.0 ⇒ 30）：上行要越过断点 +30 才换。 */
    assert(cam_gamma_slot(151 + 29, 0) == 0);               cases++;   /* +2.9 不换 */
    assert(cam_gamma_slot(151 + 30, 0) == 0);               cases++;   /* 恰在带上不换 */
    assert(cam_gamma_slot(151 + 31, 0) == 1);               cases++;   /* +3.1 换 */
    /* 下行要低于断点 −30 才换。 */
    assert(cam_gamma_slot(151 - 29, 1) == 1);               cases++;
    assert(cam_gamma_slot(151 - 30, 1) == 1);               cases++;
    assert(cam_gamma_slot(151 - 31, 1) == 0);               cases++;
    /* 停在当前档内不动。 */
    assert(cam_gamma_slot(200, 1) == 1);                    cases++;
    /* 跨两档的大跳变直接跟过去（远超迟滞带）。 */
    assert(cam_gamma_slot(5000, 0) == 3);                   cases++;
    assert(cam_gamma_slot(1, 3) == 0);                      cases++;

    /* 不抖：在每个断点附近的迟滞带里来回走，档位必须钉住不动。 */
    for (uint32_t b = 0; b + 1 < CAM_CAL_GAMMA_N; b++) {
        const uint32_t edge = cam_cal_gamma_luma_q1[b];
        uint32_t slot = b;
        for (int k = 0; k < 50; k++) {
            slot = cam_gamma_slot(edge - 29 + (uint32_t)(k % 2) * 58, slot);
            assert(slot == b);
        }
        cases++;
    }

    /* 单调扫描：env 从 0 一路涨到 4000，档位只许非减（喂回自己的输出）。 */
    {
        uint32_t slot = cam_gamma_slot(0, 99);
        for (uint32_t e = 0; e <= 4000; e++) {
            const uint32_t s = cam_gamma_slot(e, slot);
            assert(s >= slot && s < CAM_CAL_GAMMA_N);
            slot = s;
        }
        assert(slot == CAM_CAL_GAMMA_N - 1);
        cases++;
    }

    /* gamma 曲线本身（提取脚本的产物，这里再守一道）：
     * y 单调非减、末点为 255、x 的每段间隔是 2 的幂（硬件硬约束）。 */
    for (uint32_t g = 0; g < CAM_CAL_GAMMA_N; g++) {
        for (int i = 1; i < CAM_CAL_GAMMA_PTS; i++)
            assert(cam_cal_gamma_y[g][i] >= cam_cal_gamma_y[g][i - 1]);
        assert(cam_cal_gamma_y[g][CAM_CAL_GAMMA_PTS - 1] == 255);
        cases++;
    }
    {
        uint32_t prev = 0;
        for (int i = 0; i < CAM_CAL_GAMMA_PTS; i++) {
            uint32_t x = cam_cal_gamma_x[i];
            if (i == CAM_CAL_GAMMA_PTS - 1) { assert(x == 255); x = 256; }
            const uint32_t d = x - prev;
            assert(x > prev && (d & (d - 1)) == 0);
            prev = x;
        }
        cases++;
    }
}

/* ══ I. 标定表自身的守门断言 ════════════════════════════════════════ */

static void test_cal_tables(void)
{
    /* LSC 定点余量 —— §T0 的那条断言在 C 侧再守一次：
     * 2 整数位 + 8 小数位 ⇒ val 必须 < 1024，实测最大 851。 */
    uint16_t mx = 0;
    for (uint32_t s = 0; s < CAM_CAL_LSC_N; s++)
        for (int c = 0; c < 4; c++)
            for (uint32_t i = 0; i < CAM_CAL_LSC_GRIDS; i++) {
                assert(cam_cal_lsc[s][c][i] > 0 && cam_cal_lsc[s][c][i] < 1024);
                if (cam_cal_lsc[s][c][i] > mx) mx = cam_cal_lsc[s][c][i];
            }
    assert(mx == 851);                                              cases++;
    assert(CAM_CAL_LSC_GRID_X * CAM_CAL_LSC_GRID_Y == CAM_CAL_LSC_GRIDS);  cases++;

    /* 各断点表必须严格升序（选档函数的前提）。 */
    for (uint32_t i = 1; i < CAM_CAL_BF_N; i++)        assert(cam_cal_bf_gain[i] > cam_cal_bf_gain[i - 1]);
    for (uint32_t i = 1; i < CAM_CAL_DEMOSAIC_N; i++)  assert(cam_cal_demosaic_gain[i] > cam_cal_demosaic_gain[i - 1]);
    for (uint32_t i = 1; i < CAM_CAL_SHARPEN_N; i++)   assert(cam_cal_sharpen_gain[i] > cam_cal_sharpen_gain[i - 1]);
    for (uint32_t i = 1; i < CAM_CAL_CONTRAST_N; i++)  assert(cam_cal_contrast_gain[i] > cam_cal_contrast_gain[i - 1]);
    for (uint32_t i = 1; i < CAM_CAL_CCM_N; i++)       assert(cam_cal_ccm_cct[i] > cam_cal_ccm_cct[i - 1]);
    for (uint32_t i = 1; i < CAM_CAL_LSC_N; i++)       assert(cam_cal_lsc_cct[i] > cam_cal_lsc_cct[i - 1]);
    for (uint32_t i = 1; i < CAM_CAL_GAMMA_N; i++)     assert(cam_cal_gamma_luma_q1[i] > cam_cal_gamma_luma_q1[i - 1]);
    cases++;

    /* CCT 轨迹：rg 严格升序、K 严格降序（这是查表插值成立的全部前提）。 */
    for (uint32_t i = 1; i < CAM_CAL_CCT_N; i++) {
        assert(cam_cal_cct_rg[i] > cam_cal_cct_rg[i - 1]);
        assert(cam_cal_cct_k[i] < cam_cal_cct_k[i - 1]);
    }
    cases++;

    /* 白点框必须**包住**整条白点轨迹，否则轨迹两端的白点会被硬件筛掉、
     * CCT 估计在冷暖两端直接失效。
     * ⚠️ 基线文档说 awb.range 与 bp 的包围盒「数值恒等」，实测**只差一处**：
     *    awb.range.rg.min = 0.3801，而 bp 里最小的 rg 是 0.380952 ⇒ 3801 vs 3810。
     *    方向是安全的（框比轨迹宽 0.0009），所以这里验的是包含关系而不是相等。 */
    assert(CAM_CAL_RG_MIN <= cam_cal_cct_rg[0]);
    assert(CAM_CAL_RG_MAX >= cam_cal_cct_rg[CAM_CAL_CCT_N - 1]);
    assert(CAM_CAL_RG_MIN + 20 > cam_cal_cct_rg[0]);        /* 差距只有个位数，不是画歪了 */
    assert(CAM_CAL_LUM_MIN < CAM_CAL_LUM_MAX);
    cases++;

    /* §E.4 推出的增益上限 3445：1/bg_min = 10000/2903 = 3.445 ⇒ 三组测试增益都装得下。 */
    assert(10000000u / CAM_CAL_BG_MIN == 3444u || 10000000u / CAM_CAL_BG_MIN == 3445u);
    for (int g = 0; g < N_GAINS; g++) {
        assert(k_gains[g].kr >= 1000 && k_gains[g].kr <= 3445);
        assert(k_gains[g].kb >= 1000 && k_gains[g].kb <= 3445);
    }
    cases++;
}

/* ══ L. gamma 前向曲线与逆查表 ══════════════════════════════════════
 *
 * 这一组是本次「把 gamma 提前」唯一的正确性支点：ISP 一开 gamma，AE/AWB 的反馈量
 * 就得靠这张逆表还原回线性域。逆表错了的现场表现是**画面看着正常、两个闭环安静地
 * 收敛到错误的点上** —— 没有任何一条日志能把它与「传感器就这样」区分开，所以必须
 * 在宿主机上钉死。 */

/* 曲线的 17 个节点（与 cam_isp_map.c 的 gamma_node 同构，但**独立写一遍**：
 * 两边同时写错同一处的概率远低于让测试去调被测函数自己的内部实现）。 */
static void gnode(uint32_t slot, uint32_t i, uint32_t *x, uint32_t *y)
{
    if (i == 0) { *x = 0; *y = 0; return; }
    *x = (i == CAM_CAL_GAMMA_PTS) ? 256u : cam_cal_gamma_x[i - 1];
    *y = cam_cal_gamma_y[slot][i - 1];
}

static void test_gamma_curve(void)
{
    for (uint32_t s = 0; s < CAM_CAL_GAMMA_N; s++) {
        /* ── ① 端点。F(0) = 0 是硬件隐含的原点，不能靠标定表兜底。 ── */
        assert(cam_gamma_forward(s, 0) == 0);
        cases++;

        /* ── ② 前向必须精确穿过标定表的每一个节点 ──
         * 这条挡的是「段的边界算错一格」：差一格时曲线整体平移，画面只是稍亮/稍暗，
         * 肉眼判不出，但逆表会跟着整体偏。 */
        for (uint32_t i = 1; i < CAM_CAL_GAMMA_PTS; i++) {
            uint32_t x, y;
            gnode(s, i, &x, &y);
            assert(cam_gamma_forward(s, (uint8_t)x) == y);
        }
        cases++;
        /* 末点特殊：节点在 x = 256（硬件按 2 的幂编码末段），x = 255 落在段内。
         * 四档里 γ=0.5 那档恰好插值回 255，其余三档是 254 —— 都不该是 0 或 255 之外。 */
        assert(cam_gamma_forward(s, 255) >= 254);
        cases++;

        /* ── ③ 单调非减 + **近似凹**（段斜率基本单调不增）──
         *
         * 凹性不是审美要求：自检行打的「gamma后均值 >= F(线性均值)」这条判读依据，
         * 数学上就是詹森不等式，前提正是 F 凹。
         *
         * ⚠️ **官方那张 y 表是四舍五入到整数的，所以只有近似凹。** 实测四档里
         *   第 2 档（γ=0.605）在第 13 段上斜率从 10/16 回升到 11/16，是舍入抖动，
         *   不是曲线真的拐了。所以这里的界是「斜率回升不超过 1（每 16 个 x）」，
         *   即整数表能造成的最大抖动。
         *   代价量化过：曲线离自己的上凸包最远 1.22 级（第 2 档；其余三档 0.94），
         *   ⇒ 詹森那条判读要留 1 级余量，自检行的注释里写明了。
         *   **本工程钉住的第 0 档是严格凹的**（下面单独断言），所以出厂那一档上
         *   那条判读严格成立。 */
        int prev_num = -1, prev_den = 1;
        for (uint32_t x = 0; x < 255; x++) {
            assert(cam_gamma_forward(s, (uint8_t)x) <= cam_gamma_forward(s, (uint8_t)(x + 1)));
        }
        cases++;
        for (uint32_t i = 0; i < CAM_CAL_GAMMA_PTS; i++) {
            uint32_t x0, y0, x1, y1;
            gnode(s, i, &x0, &y0);
            gnode(s, i + 1, &x1, &y1);
            const int num = (int)(y1 - y0), den = (int)(x1 - x0);
            if (prev_num >= 0) {
                /* num/den <= prev_num/prev_den + 1/prev_den（舍入余量），去分母。 */
                assert((long)num * prev_den <= (long)(prev_num + 1) * den);
                if (s == 0)   /* 出厂档：严格凹，一格余量都不给 */
                    assert((long)num * prev_den <= (long)prev_num * den);
            }
            prev_num = num;
            prev_den = den;
        }
        cases++;

        /* ── ④ 曲线确实在**提亮**：γ < 1 ⇒ F(x) >= x，且中段严格大于 ──
         * ⓘ 上界只扫到 240（最后一个标定节点）。**末段是唯一的例外**：它的节点在
         *   x = 256（硬件按 2 的幂编码段长），而 x = 255 落在段内 ⇒ 插值出来是
         *   254（γ=0.5 档恰好舍入回 255）。也就是说曲线在最亮的十几级上会**低于
         *   恒等 1 级**。这不是实现的偏差，是硬件那套「末段按 256 算」的编码方式
         *   决定的，写在这里免得下次有人当成 bug 去修。 */
        for (uint32_t x = 0; x <= 240; x++)
            assert(cam_gamma_forward(s, (uint8_t)x) >= x);
        assert(cam_gamma_forward(s, 64) > 64);
        assert(cam_gamma_forward(s, 255) + 1 >= 255);
        cases++;

        /* ── ⑤ 逆表：单调、端点、往返误差 ── */
        uint8_t lut[256];
        memset(lut, 0xAA, sizeof lut);
        cam_gamma_inverse_lut(s, lut);
        assert(lut[0] == 0);
        assert(lut[255] == 255);
        for (int g = 0; g < 255; g++)
            assert(lut[g] <= lut[g + 1]);
        cases++;

        /* 往返 A：先编码再还原，必须回到原值 ±1。
         * 这是 AE/AWB 真正依赖的那条性质 —— 反馈量不能有系统性偏移。 */
        for (uint32_t x = 0; x <= 255; x++) {
            const int back = lut[cam_gamma_forward(s, (uint8_t)x)];
            assert(back - (int)x <= 1 && (int)x - back <= 1);
        }
        cases++;

        /* 往返 B：先还原再编码，±2。
         * 比 A 松一格是**物理决定的**，不是实现凑出来的：曲线在亮部压缩
         * （末段斜率 0.5）⇒ 一级 gamma 值对应两级线性值，那一格信息在 ISP 里
         * 就已经丢了。松到 3 才该怀疑实现。 */
        for (uint32_t g = 0; g <= 255; g++) {
            const int back = cam_gamma_forward(s, lut[g]);
            assert(back - (int)g <= 2 && (int)g - back <= 2);
        }
        cases++;

        /* ── ⑥ 逆表**必须逐档不同** ──
         * 挡的是「换档时逆表没跟着换」：那种 bug 下画面一切正常，只有反馈量偏了。
         * 顺带证明这张表确实是从该档曲线生成的，而不是某条写死的 γ。 */
        for (uint32_t t = 0; t < CAM_CAL_GAMMA_N; t++) {
            uint8_t other[256];
            cam_gamma_inverse_lut(t, other);
            if (t == s)
                assert(memcmp(other, lut, sizeof lut) == 0);
            else
                assert(memcmp(other, lut, sizeof lut) != 0);
        }
        cases++;

        /* ── ⑦ 交叉档的往返必须**明显**失败 ──
         * 上一条只说「表不一样」，这一条说「用错了表会错到看得见」：拿邻档的逆表
         * 去还原本档的编码值，误差必须远超 ±1 的合格线，否则第 ⑥ 条就只是在验
         * 一个无关紧要的差异。 */
        if (s + 1 < CAM_CAL_GAMMA_N) {
            uint8_t other[256];
            cam_gamma_inverse_lut(s + 1, other);
            int worst = 0;
            for (uint32_t x = 0; x <= 255; x++) {
                const int d = (int)other[cam_gamma_forward(s, (uint8_t)x)] - (int)x;
                if (d > worst) worst = d;
                if (-d > worst) worst = -d;
            }
            assert(worst > 5);
            cases++;
        }
    }

    /* ── ⑧ slot 越界钳到末档，不越界读、不崩 ── */
    {
        uint8_t a[256], b[256];
        cam_gamma_inverse_lut(CAM_CAL_GAMMA_N - 1, a);
        cam_gamma_inverse_lut(999, b);
        assert(memcmp(a, b, sizeof a) == 0);
        assert(cam_gamma_forward(999, 64) == cam_gamma_forward(CAM_CAL_GAMMA_N - 1, 64));
        cam_gamma_inverse_lut(0, NULL);          /* 不许崩 */
        cases++;
    }

    /* ── ⑨ 与解析式 γ 的差别必须**存在且很大** ──
     * 这条守的是一个容易被「优化」掉的决定：逆的是**硬件那条 16 点折线**，
     * 不是 y = 255·(x/255)^γ。两者在第一段上差到十几级（γ=0.5 档 x=1 处
     * 解析式给 16、折线给 4）—— 若哪天有人把实现换成解析式，本用例会失败，
     * 那不是测试过时，是回归。 */
    {
        /* 解析式在 x = 16 处的值：255·(16/255)^0.5 = 63.87 ⇒ 折线节点 64（两者一致，
         * 节点上本就相等）；差别全在段内。取首段中点 x = 8：
         *   解析式 255·(8/255)^0.5 = 45.2，折线 64/2 = 32 ⇒ 差 13 级。 */
        assert(cam_gamma_forward(0, 16) == 64);
        assert(cam_gamma_forward(0, 8) == 32);
        cases++;
    }
}

int main(void)
{
    test_gain_slot();
    test_to_fixed();
    test_slot_track();
    test_cct_slot();
    test_cct_nearest();
    test_cct_from_rg();
    test_ccm_interp();
    test_ccm_fold();
    test_ae();
    test_hist();
    test_env_gamma();
    test_gamma_curve();
    test_cal_tables();

    printf("OK (%d cases)\n", cases);
    return 0;
}
