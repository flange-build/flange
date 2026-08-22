/*
 * 官方标定表的运行期解释器。设计意图、定点约定与各函数契约见 cam_isp_map.h。
 * 纯逻辑，不含任何 ESP-IDF 依赖 —— 宿主机上 cc 一下就能跑。
 */
#include "cam_isp_map.h"

#include "cam_isp_cal.h"

#include <stddef.h>

/* ── 通用小工具 ────────────────────────────────────────────────── */

/* 无符号除法的四舍五入。den 必须非 0（各调用点都先判过）。 */
static uint32_t div_round_u(uint64_t num, uint32_t den)
{
    return (uint32_t)((num + den / 2) / den);
}

/* ── 选档 ──────────────────────────────────────────────────────── */

uint32_t cam_map_gain_slot(const uint16_t *gain_breaks, uint32_t n, uint32_t gain_milli)
{
    if (!gain_breaks || n == 0)
        return 0;
    uint32_t slot = 0;
    for (uint32_t i = 1; i < n; i++) {
        if (gain_milli >= gain_breaks[i])
            slot = i;
        else
            break;      /* 表是升序的，第一个够不着的之后都够不着 */
    }
    return slot;
}

uint32_t cam_map_cct_slot(const uint16_t *cct_tbl, uint32_t n, uint32_t cct_k, uint32_t *w_q8)
{
    if (w_q8)
        *w_q8 = 0;
    if (!cct_tbl || n == 0)
        return 0;
    if (n == 1 || cct_k <= cct_tbl[0])
        return 0;
    if (cct_k >= cct_tbl[n - 1])
        return n - 1;
    uint32_t i = 0;
    while (i + 1 < n - 1 && cct_k >= cct_tbl[i + 1])
        i++;
    /* 此处必有 cct_tbl[i] <= cct_k < cct_tbl[i+1]。 */
    const uint32_t lo = cct_tbl[i], hi = cct_tbl[i + 1];
    if (w_q8 && hi > lo)
        *w_q8 = (uint32_t)(((uint64_t)(cct_k - lo) * 256u) / (hi - lo));
    return i;
}

/* ── 定点转换 ──────────────────────────────────────────────────── */

bool cam_map_to_fixed(uint32_t milli, uint32_t int_bits, uint32_t dec_bits,
                      uint32_t *integer, uint32_t *decimal)
{
    const uint32_t dec_span = 1u << dec_bits;      /* 小数栅格数，如 16 / 32 */
    const uint32_t int_span = 1u << int_bits;      /* 整数部分的表达上限 + 1 */

    uint32_t whole = milli / 1000u;
    /* 四舍五入到小数栅格。(999 × 32 + 500)/1000 = 32 ⇒ 会进位，见下面一行。 */
    uint32_t frac = div_round_u((uint64_t)(milli % 1000u) * dec_span, 1000u);
    if (frac >= dec_span) {                        /* 舍上去了，进位到整数位 */
        frac = 0;
        whole++;
    }
    if (whole >= int_span) {                       /* 装不下：钳到最大可表达值 */
        *integer = int_span - 1u;
        *decimal = dec_span - 1u;
        return false;
    }
    *integer = whole;
    *decimal = frac;
    return true;
}

/* ── 带迟滞的档位跟踪器 ────────────────────────────────────────── */

bool cam_slot_changed(cam_slot_track_t *t, uint32_t want, uint32_t hyst)
{
    if (hyst == 0)
        hyst = 1;
    if (!t->primed) {                 /* 开机第一拍：不是换档，是从没配过到配上 */
        t->primed = true;
        t->cur = want;
        t->pending = want;
        t->count = 0;
        return true;
    }
    if (want == t->cur) {             /* 回到已生效的档 ⇒ 候选作废 */
        t->pending = want;
        t->count = 0;
        return false;
    }
    if (want != t->pending) {         /* 换了个新候选，重新数 */
        t->pending = want;
        t->count = 0;
    }
    if (++t->count < hyst)            /* 还没连够 hyst 拍 */
        return false;
    t->cur = want;
    t->count = 0;
    return true;
}

/* ── rg → CCT ─────────────────────────────────────────────────── */

uint32_t cam_cct_from_rg(uint32_t rg_q4)
{
    if (rg_q4 <= cam_cal_cct_rg[0])
        return cam_cal_cct_k[0];
    if (rg_q4 >= cam_cal_cct_rg[CAM_CAL_CCT_N - 1])
        return cam_cal_cct_k[CAM_CAL_CCT_N - 1];
    uint32_t i = 0;
    while (i + 2 < CAM_CAL_CCT_N && rg_q4 >= cam_cal_cct_rg[i + 1])
        i++;
    const uint32_t rlo = cam_cal_cct_rg[i], rhi = cam_cal_cct_rg[i + 1];
    const uint32_t klo = cam_cal_cct_k[i], khi = cam_cal_cct_k[i + 1];
    /* 表是「rg 升序、K 严格降序」（提取脚本已强制单调），所以这里恒有 klo > khi。 */
    const uint32_t span = rhi - rlo;                 /* 提取脚本保证 rg 严格升序 ⇒ > 0 */
    const uint32_t drop = div_round_u((uint64_t)(klo - khi) * (rg_q4 - rlo), span);
    return klo - drop;
}

/* ── CCM 插值 ─────────────────────────────────────────────────── */

void cam_ccm_at_cct(uint32_t cct_k, int32_t out_milli[9])
{
    uint32_t w = 0;
    const uint32_t i = cam_map_cct_slot(cam_cal_ccm_cct, CAM_CAL_CCM_N, cct_k, &w);
    const uint32_t j = (i + 1 < CAM_CAL_CCM_N) ? i + 1 : i;
    for (int e = 0; e < 9; e++) {
        const int32_t a = cam_cal_ccm[i][e], b = cam_cal_ccm[j][e];
        out_milli[e] = a + (int32_t)(((int64_t)(b - a) * (int64_t)w) / 256);
    }
}

/* ── CCM 折叠 + 强度钳制 ──────────────────────────────────────── */

bool cam_ccm_fold_at(const int32_t m[9], uint32_t kr, uint32_t kb,
                     uint32_t t_q8, int32_t out[9])
{
    bool ok = true;
    for (int i = 0; i < 9; i++) {
        const int32_t eye = (i % 4 == 0) ? 1000 : 0;              /* 单位阵在 0/4/8 */
        const int32_t mt  = eye + (int32_t)(((int64_t)(m[i] - eye) * (int64_t)t_q8) / 256);
        const uint32_t k  = (i % 3 == 0) ? kr : ((i % 3 == 2) ? kb : 1000u);
        const int32_t v   = (int32_t)(((int64_t)mt * (int64_t)k) / 1000);
        if (v > CAM_CCM_ABS_MAX_MILLI || v < -CAM_CCM_ABS_MAX_MILLI)
            ok = false;
        if (out)
            out[i] = v;
    }
    return ok;
}

uint32_t cam_ccm_fold_wb(const int32_t m[9], uint32_t kr, uint32_t kb, int32_t out[9])
{
    /* 可行域是 [0, t*]（P(t) 的每个元素都是 t 的线性函数，|线性| 是凸的，
     * max 取凸函数的上包络仍凸；且 t=0 必然可行，因为调用方把 kr/kb 钳在
     * [1000, 3445] ⊂ [0, 3990]）⇒ 二分有效。8 次迭代覆盖 0..256 的全部取值。 */
    uint32_t lo = 0, hi = 256;
    while (lo < hi) {
        const uint32_t mid = (lo + hi + 1) / 2;
        if (cam_ccm_fold_at(m, kr, kb, mid, NULL))
            lo = mid;
        else
            hi = mid - 1;
    }
    cam_ccm_fold_at(m, kr, kb, lo, out);
    return lo;
}

uint32_t cam_ccm_fold_wb_clamped(const int32_t m[9], uint32_t kr, uint32_t kb,
                                 uint32_t t_max, int32_t out[9], uint32_t *t_feasible)
{
    const uint32_t tf = cam_ccm_fold_wb(m, kr, kb, out);
    if (t_feasible)
        *t_feasible = tf;
    if (t_max > 256u)
        t_max = 256u;
    if (tf <= t_max)
        return tf;                       /* 总闸没起作用，out 已经是结果 */
    /* 可行域是 [0, tf] ⊇ [0, t_max] ⇒ 这一次折叠必然可行，返回值不必再看。 */
    (void)cam_ccm_fold_at(m, kr, kb, t_max, out);
    return t_max;
}

/* ── AE 加权均值 + quorum 剔除 ────────────────────────────────── */

uint8_t cam_ae_weighted_mean(const uint8_t lum[25], uint8_t *n_dark, uint8_t *n_bright)
{
    uint32_t nd = 0, nb = 0;
    if (!lum) {
        if (n_dark)   *n_dark = 0;
        if (n_bright) *n_bright = 0;
        return 0;
    }
    for (int i = 0; i < 25; i++) {
        if (lum[i] < CAM_CAL_AE_LOW_THRESH)  nd++;
        if (lum[i] > CAM_CAL_AE_HIGH_THRESH) nb++;
    }
    if (n_dark)   *n_dark   = (uint8_t)nd;
    if (n_bright) *n_bright = (uint8_t)nb;

    /* 官方语义是「计数达标才进保护分支」：不到 quorum 就一块都不剔。 */
    const bool drop_dark   = (nd >= CAM_CAL_AE_LOW_REGIONS);
    const bool drop_bright = (nb >= CAM_CAL_AE_HIGH_REGIONS);

    uint32_t wsum = 0, acc = 0, plain = 0;
    for (int i = 0; i < 25; i++) {
        plain += lum[i];
        if (drop_dark && lum[i] < CAM_CAL_AE_LOW_THRESH)
            continue;
        if (drop_bright && lum[i] > CAM_CAL_AE_HIGH_THRESH)
            continue;
        const uint32_t w = cam_cal_ae_weight[i];
        wsum += w;
        acc  += w * lum[i];
    }
    if (wsum == 0)
        return (uint8_t)div_round_u(plain, 25);      /* 全被剔除 ⇒ 退回无权平均 */
    return (uint8_t)div_round_u(acc, wsum);
}

/* ── 直方图归约 ───────────────────────────────────────────────── */

void cam_hist_stats(const uint32_t bins[16], uint8_t *mean, uint8_t *bright_pct,
                    uint8_t *dark_pct)
{
    if (mean)       *mean = 0;
    if (bright_pct) *bright_pct = 0;
    if (dark_pct)   *dark_pct = 0;
    if (!bins)
        return;

    uint64_t total = 0, acc = 0;
    for (int i = 0; i < 16; i++) {
        total += bins[i];
        acc   += (uint64_t)bins[i] * (uint64_t)(16 * i + 8);
    }
    if (total == 0)
        return;

    if (mean)
        *mean = (uint8_t)((acc + total / 2) / total);
    if (dark_pct)
        *dark_pct = (uint8_t)(((uint64_t)bins[0] * 100u + total / 2) / total);
    if (bright_pct)
        *bright_pct = (uint8_t)(((uint64_t)bins[15] * 100u + total / 2) / total);
}

/* ── env.luma 与 gamma 选档 ───────────────────────────────────── */

uint32_t cam_env_luma_q1(uint32_t ev, uint8_t scene_mean, uint8_t ae_target)
{
    if (ev == 0 || ae_target == 0)
        return 0;
    const uint64_t num = (uint64_t)CAM_CAL_ENV_K * 10u * (uint64_t)scene_mean;
    const uint64_t den = (uint64_t)ae_target * (uint64_t)ev;
    return (uint32_t)((num + den / 2) / den);
}

static uint32_t gamma_slot_raw(uint32_t env_q1)
{
    for (uint32_t i = 0; i < CAM_CAL_GAMMA_N; i++) {
        if (env_q1 <= cam_cal_gamma_luma_q1[i])
            return i;
    }
    return CAM_CAL_GAMMA_N - 1;
}

uint32_t cam_gamma_slot(uint32_t env_q1, uint32_t cur_slot)
{
    const uint32_t want = gamma_slot_raw(env_q1);
    if (cur_slot >= CAM_CAL_GAMMA_N)
        return want;                                  /* 开机第一拍，没有迟滞可言 */
    if (want == cur_slot)
        return cur_slot;
    if (want > cur_slot) {
        /* 上行：必须越过 cur 档的上界再加一个迟滞带。 */
        if (env_q1 > (uint32_t)cam_cal_gamma_luma_q1[cur_slot] + CAM_CAL_GAMMA_MIN_STEP_Q1)
            return want;
    } else {
        /* 下行：必须低于 cur 档的下界（= cur-1 档的上界）再减一个迟滞带。 */
        if (env_q1 + CAM_CAL_GAMMA_MIN_STEP_Q1 < (uint32_t)cam_cal_gamma_luma_q1[cur_slot - 1])
            return want;
    }
    return cur_slot;
}

/* ── gamma 前向/逆变换 ────────────────────────────────────────────
 *
 * 曲线的 17 个节点。i = 0 是硬件隐含的原点 (0,0)；i = 1..16 是标定表的 16 个点，
 * 其中 i = 16 的 x 取 **256** 而不是表里的 255 —— 硬件按段长 256−240 = 16
 * （2 的幂）编码最后一段，末点的 y 是 x = 256 处的值。
 */
static void gamma_node(uint32_t slot, uint32_t i, uint32_t *x, uint32_t *y)
{
    if (i == 0) {
        *x = 0;
        *y = 0;
        return;
    }
    *x = (i == CAM_CAL_GAMMA_PTS) ? 256u : cam_cal_gamma_x[i - 1];
    *y = cam_cal_gamma_y[slot][i - 1];
}

static uint32_t gamma_slot_clamp(uint32_t slot)
{
    return slot < CAM_CAL_GAMMA_N ? slot : CAM_CAL_GAMMA_N - 1;
}

uint8_t cam_gamma_forward(uint32_t slot, uint8_t x)
{
    const uint32_t s = gamma_slot_clamp(slot);

    for (uint32_t i = 0; i < CAM_CAL_GAMMA_PTS; i++) {
        uint32_t x0, y0, x1, y1;
        gamma_node(s, i, &x0, &y0);
        gamma_node(s, i + 1, &x1, &y1);
        if ((uint32_t)x < x1) {
            /* 段内线性插值，**四舍五入**而不是截断：硬件用移位（截断）还是带舍入
             * 的乘加，TRM 与 IDF 都没写死 —— 差别至多 1 级。选四舍五入是因为逆表
             * 由同一个模型生成，两侧一致比两侧各自「更像硬件」更要紧（往返一致性
             * 是控制环真正依赖的性质，绝对值差 1 级不进任何判据）。 */
            const uint32_t dx = x1 - x0, dy = y1 - y0;
            return (uint8_t)(y0 + (((uint32_t)x - x0) * dy + dx / 2u) / dx);
        }
    }
    return 255;   /* 走不到：末段的 x1 = 256 > 255 */
}

void cam_gamma_inverse_lut(uint32_t slot, uint8_t lut[256])
{
    if (!lut)
        return;
    const uint32_t s = gamma_slot_clamp(slot);

    for (uint32_t g = 0; g < 256; g++) {
        uint32_t v = 255;
        for (uint32_t i = 0; i < CAM_CAL_GAMMA_PTS; i++) {
            uint32_t x0, y0, x1, y1;
            gamma_node(s, i, &x0, &y0);
            gamma_node(s, i + 1, &x1, &y1);
            if (g > y1)
                continue;
            /* y 在本段内。dy == 0（曲线在这一段是平的）时取段起点：那一段的所有
             * 线性值都编码成同一个 g，取哪个都是猜，取最小的那个不会高估亮度 ——
             * 高估会让 AE 以为够亮而停止加曝光。官方四档都没有平段，这是守门人。 */
            const uint32_t dx = x1 - x0, dy = y1 - y0;
            v = (dy == 0) ? x0 : (x0 + ((g - y0) * dx + dy / 2u) / dy);
            break;
        }
        lut[g] = (uint8_t)(v > 255u ? 255u : v);
    }
}
